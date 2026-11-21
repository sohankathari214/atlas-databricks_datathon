import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const execute = promisify(execFile);
let token;
let expires = 0;

function workspaceUrl() {
  const host = process.env.DATABRICKS_HOST || '';
  return (host.includes('://') ? host : `https://${host}`).replace(/\/$/, '');
}

async function appToken() {
  if (token && expires > Date.now()) return token;
  const host = workspaceUrl();
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

export async function databricksRequest(path, body) {
  if (process.env.DATABRICKS_PROFILE && !process.env.DATABRICKS_CLIENT_SECRET) {
    const command = ['api', body ? 'post' : 'get', path, '-p', process.env.DATABRICKS_PROFILE, '-o', 'json'];
    if (body) command.push('--json', JSON.stringify(body));
    const { stdout } = await execute(process.env.DATABRICKS_CLI || 'databricks', command, { timeout: 40000 });
    return JSON.parse(stdout);
  }
  const response = await fetch(`${workspaceUrl()}${path}`, {
    method: body ? 'POST' : 'GET',
    headers: { Authorization: `Bearer ${await appToken()}`, 'Content-Type': 'application/json' },
    body: body && JSON.stringify(body),
    signal: AbortSignal.timeout(40000),
  });
  if (!response.ok) throw new Error(`Databricks API HTTP ${response.status}`);
  return response.json();
}

export async function queryJson(statement, params) {
  const path = '/api/2.0/sql/statements';
  let result = await databricksRequest(path, {
    warehouse_id: process.env.WAREHOUSE_ID || '745fb903b957561a',
    statement,
    parameters: Object.entries(params).map(([name, value]) => ({ name, value, type: 'STRING' })),
    wait_timeout: '10s',
  });
  for (let attempts = 0; ['PENDING', 'RUNNING'].includes(result.status.state) && attempts < 18; attempts++) {
    await new Promise(resolve => setTimeout(resolve, 1200));
    result = await databricksRequest(`${path}/${result.statement_id}`);
  }
  if (result.status.state !== 'SUCCEEDED') {
    throw new Error(result.status.error?.message ?? `SQL state ${result.status.state}`);
  }
  const payload = result.result?.data_array?.[0]?.[0];
  if (!payload) throw new Error('Databricks SQL returned no JSON payload');
  return JSON.parse(payload);
}
