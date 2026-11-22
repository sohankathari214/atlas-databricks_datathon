import { execFileSync } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { loadEnvFile } from 'node:process';
import { fileURLToPath } from 'node:url';
import { localPhoneConfig, relayPhoneConfig, studioRequest, validPhoneConfig, validRelayConfig } from '../backend/phone-check.mjs';

const workspace = 'https://dbc-069c8426-ea2f.cloud.databricks.com';
const scope = 'referral-voice';
const friendlyName = 'Virtue Datathon Hindi Dialysis';
const cli = process.env.DATABRICKS_CLI || 'databricks';
const profile = process.env.DATABRICKS_PROFILE || 'virtue-datathon';

async function publishStudio() {
  const config = localPhoneConfig();
  if (!validPhoneConfig(config)) throw new Error('Set the four Twilio values in .env. Use distinct E.164 numbers.');
  const definition = await readFile(new URL('./hindi-dialysis-flow.json', import.meta.url), 'utf8');
  const fields = { FriendlyName: friendlyName, Status: 'published', Definition: definition };
  const validation = await studioRequest(config, '/Flows/Validate', fields);
  if (!validation.valid) throw new Error('Twilio did not validate the Hindi flow.');

  if (config.flow && !/^FW[\da-f]{32}$/i.test(config.flow)) throw new Error('TWILIO_FLOW_SID must be a Studio Flow SID.');
  const list = config.flow ? [] : (await studioRequest(config, '/Flows?PageSize=50')).flows;
  const existing = list.find(flow => flow.friendly_name === friendlyName);
  const existingSid = config.flow || existing?.sid;
  const flow = existingSid
    ? await studioRequest(config, '/Flows/' + existingSid, fields)
    : await studioRequest(config, '/Flows', fields);
  if (flow.status !== 'published' || !/^FW[\da-f]{32}$/i.test(flow.sid)) throw new Error('The Hindi flow is not published.');
  config.flow = flow.sid;
  return config;
}

async function configure() {
  loadEnvFile(fileURLToPath(new URL('../.env', import.meta.url)));
  const relay = relayPhoneConfig();
  const config = relay.relayUrl || relay.relayToken ? relay : await publishStudio();
  if (config === relay) {
    if (!validRelayConfig(relay)) throw new Error('The voice relay configuration is incomplete.');
    const health = await fetch(relay.relayUrl + '/health', {
      headers: { Authorization: 'Bearer ' + relay.relayToken },
      signal: AbortSignal.timeout(8000),
    });
    if (!health.ok || (await health.json()).status !== 'ready') throw new Error('The voice relay is unavailable.');
  }

  const auth = JSON.parse(execFileSync(cli, ['auth', 'token', '--host', workspace, '-p', profile], { encoding: 'utf8' }));
  if (!auth.access_token) throw new Error('Could not obtain Databricks workspace credentials.');
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
  await api('/api/2.0/secrets/put', { scope, key: 'twilio-studio', string_value: JSON.stringify(config) });
  console.log('Saved the hosted app voice configuration. No call was placed.');
}

configure().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});
