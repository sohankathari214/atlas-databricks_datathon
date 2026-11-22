import { translatePage, validTranslation } from './page-translation.mjs';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { loadEnvFile } from 'node:process';
import { emergencyRoute, interpretCare } from './care-intake.mjs';
import { emergencySigns } from '../web/care-routing.js';
import { databricksRequest } from './databricks.mjs';
import { searchReferral, serviceCatalog, referralContext } from './referrals.mjs';

if (!process.env.DATABRICKS_APP_PORT) {
  try {
    loadEnvFile(fileURLToPath(new URL('../.env', import.meta.url)));
  } catch (error) {
    if (error.code !== 'ENOENT') throw error;
  }
}

const services = new Set(['mri', 'dialysis', 'c_section', 'nicu', 'cardiac_surgery', 'burn_care', 'trauma_care']);
const staticFiles = {
  '/': ['index.html', 'text/html'],
  '/style.css': ['style.css', 'text/css'],
  '/page-language.js': ['page-language.js', 'text/javascript'],
  '/app.js': ['app.js', 'text/javascript'],
  '/care-routing.js': ['care-routing.js', 'text/javascript'],
};
let cloudKey;
let keyExpires = 0;
async function openAIKey() {
  if (process.env.OPENAI_API_KEY?.trim()) return process.env.OPENAI_API_KEY.trim();
  if (!process.env.DATABRICKS_APP_PORT) return '';
  if (keyExpires > Date.now()) return cloudKey;
  try {
    const secret = await databricksRequest('/api/2.0/secrets/get?scope=referral-llm&key=openai-api-key');
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
  const submittedAt = new Date();
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
  const [result, context] = await Promise.all([
    searchReferral(location, interpretation.service),
    referralContext(submittedAt).catch(() => null),
  ]);
  return json(200, { ...result, interpretation, context });
}

function send(response, code, type, content) {
  response.writeHead(code, {
    'Content-Type': `${type}; charset=utf-8`,
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; frame-src https://www.google.com/maps https://www.google.com/maps/embed; base-uri 'none'; object-src 'none'",
  });
  response.end(content);
}

const server = createServer(async (request, response) => {
  const url = new URL(request.url, 'http://localhost');
  try {
    if (url.pathname === '/health') return send(response, 200, 'text/plain', 'ok');
    if (url.pathname === '/api/page-translation') {
      const json = (code, data) => send(response, code, 'application/json', JSON.stringify(data));
      if (request.method !== 'POST') return json(405, {});
      if (request.headers['content-type']?.split(';')[0].trim().toLowerCase() !== 'application/json') return json(415, {});
      const input = await readIntake(request);
      if (!validTranslation(input)) return json(400, {});
      try {
        const key = await openAIKey();
        if (!key) return json(503, {});
        return json(200, { strings: await translatePage(input, key, process.env.OPENAI_MODEL || 'gpt-6-luna') });
      } catch {
        return json(503, {});
      }
    }
    if (url.pathname === '/api/referral') {
      if (request.method === 'POST') return await handleIntake(request, response);
      if (request.method !== 'GET') return send(response, 405, 'application/json', '{"error":"Unsupported request method."}');
      const location = url.searchParams.get('location')?.trim();
      const service = url.searchParams.get('service');
      if (!location || location.length > 100 || !services.has(service)) {
        return send(response, 400, 'application/json', '{"error":"Enter a location and choose one of the seven services."}');
      }
      return send(response, 200, 'application/json', JSON.stringify(await searchReferral(location, service)));
    }
    const file = Object.hasOwn(staticFiles, url.pathname) && staticFiles[url.pathname];
    if (file) return send(response, 200, file[1], await readFile(new URL(`../web/${file[0]}`, import.meta.url)));
    return send(response, 404, 'text/plain', 'Page not found');
  } catch (error) {
    console.error('Referral request failed:', error.message);
    return send(response, 503, 'application/json', '{"error":"Databricks could not load the results. Retry the search."}');
  }
});
const port = Number(process.env.DATABRICKS_APP_PORT || process.env.PORT || 4173);
server.listen(port, process.env.DATABRICKS_APP_PORT ? '0.0.0.0' : '127.0.0.1',
  () => {
    console.log(`Atlas listening on port ${port}`);
    if (process.env.DATABRICKS_APP_PORT) {
      serviceCatalog().catch(error => console.error('Databricks catalog check failed:', error.message));
    }
  });

process.on('SIGTERM', () => server.close(() => process.exit(0)));
