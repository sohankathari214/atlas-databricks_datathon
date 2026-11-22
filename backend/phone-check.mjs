import { randomUUID } from 'node:crypto';
import { databricksRequest } from './databricks.mjs';

const sid = /^AC[\da-f]{32}$/i;
const flowSid = /^FW[\da-f]{32}$/i;
const executionSid = /^FN[\da-f]{32}$/i;
const testNumber = /^\+[1-9]\d{7,14}$/;
const secretPath = '/api/2.0/secrets/get?scope=referral-voice&key=twilio-studio';
const attempts = new Map();
const limit = 4;
const lifetime = 75000;
let starting = false;

export function localPhoneConfig(env = process.env) {
  return {
    account: env.TWILIO_ACCOUNT_SID?.trim(),
    token: env.TWILIO_AUTH_TOKEN?.trim(),
    from: env.TWILIO_FROM_NUMBER?.trim(),
    to: env.TWILIO_TEST_TO_NUMBER?.trim(),
    flow: env.TWILIO_FLOW_SID?.trim(),
  };
}

export function validPhoneConfig(config) {
  return sid.test(config?.account ?? '') && /^[\da-f]{32}$/i.test(config?.token ?? '')
    && testNumber.test(config?.from ?? '') && testNumber.test(config?.to ?? '') && config.from !== config.to;
}

export function relayPhoneConfig(env = process.env) {
  return { relayUrl: env.REFERRAL_VOICE_RELAY_URL, relayToken: env.REFERRAL_VOICE_RELAY_TOKEN };
}

export function validRelayConfig(config) {
  return /^https:\/\/[a-z0-9.-]+(?::\d+)?$/i.test(config?.relayUrl ?? '')
    && /^[\da-f]{64}$/i.test(config?.relayToken ?? '');
}

async function phoneConfig() {
  const relay = relayPhoneConfig();
  if (validRelayConfig(relay)) return relay;
  let config = localPhoneConfig();
  if (process.env.DATABRICKS_APP_PORT && !validPhoneConfig(config)) {
    try {
      const secret = await databricksRequest(secretPath);
      config = JSON.parse(Buffer.from(secret.value, 'base64').toString('utf8'));
    } catch {
      return null;
    }
  }
  if (validRelayConfig(config)) return config;
  return validPhoneConfig(config) && flowSid.test(config.flow ?? '') ? config : null;
}

async function relayRequest(config, path, method = 'GET') {
  const response = await fetch(config.relayUrl + path, {
    method,
    headers: { Authorization: `Bearer ${config.relayToken}` },
    signal: AbortSignal.timeout(12000),
  });
  if (!response.ok) throw new Error(`Voice relay HTTP ${response.status}`);
  return response.json();
}

export async function studioRequest(config, path, fields, request = fetch) {
  const auth = Buffer.from(`${config.account}:${config.token}`).toString('base64');
  const response = await request('https://studio.twilio.com/v2' + path, {
    method: fields ? 'POST' : 'GET',
    headers: { Authorization: `Basic ${auth}`, 'Content-Type': 'application/x-www-form-urlencoded' },
    body: fields && new URLSearchParams(fields),
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(`Twilio HTTP ${response.status} (code ${Number(body.code) || 'unknown'})`);
    error.providerCode = body.code;
    throw error;
  }
  return response.json();
}

export function readKeypadResult(payload, execution) {
  const digit = String(payload.context?.flow?.variables?.dialysis_answer
    ?? payload.context?.widgets?.dialysis_reply?.Digits ?? '').trim();
  if (digit === '1') return 'yes';
  if (digit === '2') return 'no';
  if (digit || (execution.status === 'ended')) return 'unconfirmed';
  return 'pending';
}

export async function startPhoneCheck() {
  const now = Date.now();
  for (const attempt of attempts.values()) {
    if (attempt.status === 'pending' && attempt.deadline <= now) attempt.status = 'unconfirmed';
  }
  if (starting || [...attempts.values()].some(attempt => attempt.status === 'pending')) return { status: 'busy' };
  if (attempts.size >= limit) return { status: 'limit' };
  starting = true;
  try {
    const config = await phoneConfig();
    if (!config) return { status: 'setup_required' };
    if (validRelayConfig(config)) return await relayRequest(config, '/call', 'POST');
    // The browser never provides a destination or caller ID.
    const path = `/Flows/${config.flow}/Executions`;
    const execution = await studioRequest(config, path, { From: config.from, To: config.to });
    if (!executionSid.test(execution.sid ?? '')) throw new Error('Twilio returned an invalid execution ID.');
    const id = randomUUID();
    attempts.set(id, { status: 'pending', path: `${path}/${execution.sid}`, config, deadline: Date.now() + lifetime });
    return { id, status: 'pending' };
  } finally {
    starting = false;
  }
}

export async function phoneCheckStatus(id) {
  const attempt = attempts.get(id);
  if (!attempt) {
    if (!/^[\da-f-]{36}$/i.test(id ?? '')) return { status: 'not_found' };
    const config = await phoneConfig();
    return validRelayConfig(config) ? relayRequest(config, '/call/' + id) : { status: 'not_found' };
  }
  if (attempt.status === 'pending') {
    if (Date.now() >= attempt.deadline) attempt.status = 'unconfirmed';
    else {
      const execution = await studioRequest(attempt.config, attempt.path);
      const payload = await studioRequest(attempt.config, attempt.path + '/Context');
      attempt.status = readKeypadResult(payload, execution);
    }
  }
  return { status: attempt.status };
}
