import { execFileSync } from 'node:child_process';
import { loadEnvFile } from 'node:process';
import { fileURLToPath } from 'node:url';

const workspace = 'https://dbc-069c8426-ea2f.cloud.databricks.com';
const scope = 'referral-llm';
const key = 'openai-api-key';
const cli = process.env.DATABRICKS_CLI || 'databricks';
const profile = process.env.DATABRICKS_PROFILE || 'virtue-datathon';

async function configure() {
  loadEnvFile(fileURLToPath(new URL('../../.env', import.meta.url)));
  const apiKey = process.env.OPENAI_API_KEY?.trim();
  if (!apiKey || !apiKey.startsWith('sk-')) throw new Error('Set OPENAI_API_KEY in the root .env file first.');
  const auth = JSON.parse(execFileSync(cli, ['auth', 'token', '--host', workspace, '-p', profile], { encoding: 'utf8' }));
  if (!auth.access_token) throw new Error('Could not obtain workspace OAuth credentials.');
  async function api(path, body) {
    const response = await fetch(workspace + path, {
      method: body ? 'POST' : 'GET',
      headers: { Authorization: `Bearer ${auth.access_token}`, 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(20000),
      body: body && JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(`Databricks ${path} HTTP ${response.status} ${result.error_code || ''}`);
    return result;
  }
  const app = await api('/api/2.0/apps/find-the-right-care');
  if (!app.service_principal_client_id) throw new Error('The app service principal is missing.');
  const scopes = await api('/api/2.0/secrets/scopes/list');
  if (!scopes.scopes?.some(item => item.name === scope)) {
    await api('/api/2.0/secrets/scopes/create', { scope });
  }
  await api('/api/2.0/secrets/acls/put', { scope, principal: app.service_principal_client_id, permission: 'READ' });
  await api('/api/2.0/secrets/put', { scope, key, string_value: apiKey });
  console.log('Stored the OpenAI key in the app’s dedicated Databricks secret scope.');
}

configure().catch(error => {
  // Credential values and provider response messages are never printed.
  console.error(error.message);
  process.exitCode = 1;
});
