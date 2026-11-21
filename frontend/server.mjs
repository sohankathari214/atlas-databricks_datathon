import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import { loadEnvFile } from 'node:process';
import { emergencyRoute, interpretCare } from './care-intake.mjs';
import { emergencySigns } from './public/care-routing.js';

if (!process.env.DATABRICKS_APP_PORT) {
  try {
    loadEnvFile(fileURLToPath(new URL('../.env', import.meta.url)));
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
}

const execute = promisify(execFile);
const workspaceHost = process.env.DATABRICKS_HOST || '';
const host = (workspaceHost.includes('://') ? workspaceHost : `https://${workspaceHost}`).replace(/\/$/, '');
const warehouse = process.env.WAREHOUSE_ID || '745fb903b957561a';
const services = new Set(['mri', 'dialysis', 'c_section', 'nicu', 'cardiac_surgery', 'burn_care', 'trauma_care']);
const scenarios = new Set(['palwal', 'bhagalpur']);
const staticFiles = {
  '/': ['index.html', 'text/html'],
  '/style.css': ['style.css', 'text/css'],
  '/app.js': ['app.js', 'text/javascript'],
  '/care-routing.js': ['care-routing.js', 'text/javascript'],
};
let token;
let expires = 0;

async function appToken() {
  if (token && expires > Date.now()) return token;
  const basic = Buffer.from(`${process.env.DATABRICKS_CLIENT_ID}:${process.env.DATABRICKS_CLIENT_SECRET}`).toString('base64');
  const response = await fetch(`${host}/oidc/v1/token`, {
    method: 'POST',
    headers: { Authorization: `Basic ${basic}` },
    body: new URLSearchParams({ grant_type: 'client_credentials', scope: 'all-apis' }),
    signal: AbortSignal.timeout(12000),
  });
  if (!response.ok) throw new Error(`Databricks OAuth HTTP ${response.status}`);
  const data = await response.json();
  token = data.access_token;
  expires = Date.now() + (data.expires_in - 60) * 1000;
  return token;
}

async function databricks(path, body) {
  if (process.env.DATABRICKS_PROFILE && !process.env.DATABRICKS_CLIENT_SECRET) {
    const command = ['api', body ? 'post' : 'get', path, '-p', process.env.DATABRICKS_PROFILE, '-o', 'json'];
    if (body) command.push('--json', JSON.stringify(body));
    const { stdout } = await execute(process.env.DATABRICKS_CLI || 'databricks', command, { timeout: 40000 });
    return JSON.parse(stdout);
  }
  const response = await fetch(`${host}${path}`, {
    method: body ? 'POST' : 'GET',
    headers: { Authorization: `Bearer ${await appToken()}`, 'Content-Type': 'application/json' },
    body: body && JSON.stringify(body),
    signal: AbortSignal.timeout(40000),
  });
  if (!response.ok) throw new Error(`Databricks SQL HTTP ${response.status}`);
  return response.json();
}

async function queryReferral(statement, params) {
  const path = '/api/2.0/sql/statements';
  let result = await databricks(path, {
    warehouse_id: warehouse,
    statement,
    parameters: Object.entries(params).map(([name, value]) => ({ name, value, type: 'STRING' })),
    wait_timeout: '10s',
  });
  for (let attempts = 0; ['PENDING', 'RUNNING'].includes(result.status.state) && attempts < 18; attempts++) {
    await new Promise(resolve => setTimeout(resolve, 1200));
    result = await databricks(`${path}/${result.statement_id}`);
  }
  if (result.status.state !== 'SUCCEEDED') {
    throw new Error(result.status.error?.message ?? `SQL state ${result.status.state}`);
  }
  const payload = result.result?.data_array?.[0]?.[0];
  if (!payload) throw new Error('Published scenario is missing');
  return JSON.parse(payload);
}

function readScenario(scenario) {
  return queryReferral('SELECT payload FROM workspace.referral_verification.frontend_scenarios WHERE scenario = :scenario', { scenario });
}

function searchReferral(location, service) {
  return queryReferral('SELECT payload FROM workspace.referral_verification.search_referrals(:location, :service)', { location, service });
}

let catalogCache;
let catalogExpires = 0;
async function serviceCatalog() {
  if (catalogCache && catalogExpires > Date.now()) return catalogCache;
  const catalog = await queryReferral(
    'SELECT payload FROM workspace.referral_verification.referral_service_catalog()', {},
  );
  if (!catalog.length) throw new Error('Databricks service catalog is empty');
  catalogCache = catalog;
  catalogExpires = Date.now() + 300000;
  return catalog;
}

let cloudKey;
let keyExpires = 0;
async function openAIKey() {
  if (process.env.OPENAI_API_KEY?.trim()) return process.env.OPENAI_API_KEY.trim();
  if (!process.env.DATABRICKS_APP_PORT) return '';
  if (keyExpires > Date.now()) return cloudKey;
  try {
    const secret = await databricks('/api/2.0/secrets/get?scope=referral-llm&key=openai-api-key');
    cloudKey = Buffer.from(secret.value, 'base64').toString('utf8').trim();
    keyExpires = Date.now() + 60000;
  } catch {
    cloudKey = '';
    keyExpires = Date.now() + 15000;
  }
  return cloudKey;
}

async function readIntake(request) {
  const chunks = [];
  let bytes = 0;
  for await (const chunk of request.iterator({ destroyOnReturn: false })) {
    bytes += chunk.length;
    if (bytes > 4096) return null;
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    return null;
  }
}

async function handleIntake(request, response) {
  if (request.headers['content-type']?.split(';')[0].trim().toLowerCase() !== 'application/json') {
    return send(response, 415, 'application/json', '{"error":"Send the search as JSON."}');
  }
  const input = await readIntake(request);
  const location = typeof input?.location === 'string' ? input.location.trim() : '';
  const problem = typeof input?.problem === 'string' ? input.problem.trim() : '';
  const json = (code, value) => send(response, code, 'application/json', JSON.stringify(value));
  if (!location || location.length > 100 || !problem || problem.length > 300) {
    return json(400, { error: 'Enter a location and describe the care or service in 300 characters or fewer.' });
  }

  let interpretation;
  try {
    interpretation = emergencySigns(problem) ? emergencyRoute() : await interpretCare(problem, await serviceCatalog(), {
      apiKey: await openAIKey(), model: process.env.OPENAI_MODEL || 'gpt-6-luna',
    });
  } catch {
    return json(503, { error: 'The OpenAI interpretation service is unavailable. Try again.' });
  }
  if (interpretation.status === 'clarify') {
    return json(200, { message: 'Enter one specific service to search for, such as an MRI scan or a dialysis appointment.' });
  }
  if (interpretation.status === 'unsupported') {
    const primary = (await serviceCatalog()).find(service => service.id === 'primary_care');
    interpretation = { status: 'match', service: primary.id, label: primary.label,
      keywords: primary.keywords.slice(0, 3), method: 'fallback' };
  }
  if (interpretation.status === 'setup_required') {
    return json(200, { message: 'Free-text interpretation needs an OpenAI API key. Exact service terms still work.' });
  }

  if (interpretation.service === 'emergency_care') {
    try {
      const result = await searchReferral(location, interpretation.service);
      return json(200, { ...result, interpretation, emergency: true });
    } catch {
      return json(200, { emergency: true, interpretation, message: 'The directory could not load nearby emergency department listings.' });
    }
  }
  const result = await searchReferral(location, interpretation.service);
  return json(200, { ...result, interpretation });
}

function send(response, code, type, content) {
  response.writeHead(code, {
    'Content-Type': `${type}; charset=utf-8`,
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; base-uri 'none'; object-src 'none'",
  });
  response.end(content);
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url, 'http://localhost');
  try {
    if (url.pathname === '/health') return send(response, 200, 'text/plain', 'ok');
    if (url.pathname === '/api/referral') {
      if (request.method === 'POST') return await handleIntake(request, response);
      if (request.method !== 'GET') return send(response, 405, 'application/json', '{"error":"Unsupported request method."}');
      const scenario = url.searchParams.get('scenario');
      const location = url.searchParams.get('location')?.trim();
      const service = url.searchParams.get('service');
      if (scenarios.has(scenario)) return send(response, 200, 'application/json', JSON.stringify(await readScenario(scenario)));
      if (!location || location.length > 100 || !services.has(service)) {
        return send(response, 400, 'application/json', '{"error":"Enter a location and choose one of the seven services."}');
      }
      return send(response, 200, 'application/json', JSON.stringify(await searchReferral(location, service)));
    }
    const file = Object.hasOwn(staticFiles, url.pathname) && staticFiles[url.pathname];
    if (file) return send(response, 200, file[1], await readFile(new URL(`./public/${file[0]}`, import.meta.url)));
    return send(response, 404, 'text/plain', 'Page not found');
  } catch (error) {
    console.error('Referral request failed:', error.message);
    return send(response, 503, 'application/json', '{"error":"Databricks could not load the results. Retry the search."}');
  }
});
const port = Number(process.env.DATABRICKS_APP_PORT || process.env.PORT || 4173);
server.listen(port, process.env.DATABRICKS_APP_PORT ? '0.0.0.0' : '127.0.0.1',
  () => {
    console.log(`Find the right care listening on port ${port}`);
    if (process.env.DATABRICKS_APP_PORT) {
      serviceCatalog().then(catalog => searchReferral('Jaipur, Rajasthan', catalog.find(service => service.id === 'c_section').id))
        .then(() => console.log('Databricks service catalog and live Jaipur C-section query verified.'))
        .catch(error => console.error('Databricks startup query failed:', error.message));
    }
  });

process.on('SIGTERM', () => server.close(() => process.exit(0)));
