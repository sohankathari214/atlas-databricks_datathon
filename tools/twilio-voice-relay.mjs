import { createHmac, randomUUID, timingSafeEqual } from 'node:crypto';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { loadEnvFile } from 'node:process';
import { fileURLToPath } from 'node:url';
import { localPhoneConfig, relayPhoneConfig, validPhoneConfig, validRelayConfig } from '../backend/phone-check.mjs';

loadEnvFile(fileURLToPath(new URL('../.env', import.meta.url)));
const config = localPhoneConfig();
const relay = relayPhoneConfig();
if (!validPhoneConfig(config) || !validRelayConfig(relay)) throw new Error('The local Twilio or voice relay configuration is incomplete.');
const definition = JSON.parse(await readFile(new URL('./hindi-dialysis-flow.json', import.meta.url), 'utf8'));
const prompt = definition.states.find(state => state.name === 'dialysis_reply').properties.say;
const auth = Buffer.from(config.account + ':' + config.token).toString('base64');
const calls = new Map();
const maxCalls = 4;
const validity = 75000;

function equals(left, right) {
  const first = Buffer.from(left ?? '');
  const second = Buffer.from(right);
  return first.length === second.length && timingSafeEqual(first, second);
}

function webhookKey(path) {
  return createHmac('sha256', relay.relayToken).update(path).digest('hex');
}

function webhookUrl(path) {
  return relay.relayUrl + path + '?key=' + webhookKey(path);
}

function state(call) {
  if (!call) return 'not_found';
  if (call.status === 'pending' && Date.now() >= call.expires) call.status = 'unconfirmed';
  return call.status;
}

function json(res, body, code = 200) {
  res.writeHead(code, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' });
  res.end(JSON.stringify(body));
}

async function dial(res) {
  if ([...calls.values()].some(call => state(call) === 'pending')) return json(res, { status: 'busy' });
  if (calls.size >= maxCalls) return json(res, { status: 'limit' });
  const id = randomUUID();
  const call = { status: 'pending', expires: Date.now() + validity };
  calls.set(id, call);
  try {
    const response = await fetch('https://api.twilio.com/2010-04-01/Accounts/' + config.account + '/Calls.json', {
      method: 'POST',
      headers: { Authorization: 'Basic ' + auth, 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ From: config.from, To: config.to, Url: webhookUrl('/twiml/' + id) }),
      signal: AbortSignal.timeout(9500),
    });
    const result = await response.json();
    if (!response.ok || !/^CA[\da-f]{32}$/i.test(result.sid ?? '')) {
      console.error('Twilio rejected the voice request', response.status, Number(result.code) || '');
      call.status = 'provider_error';
      return json(res, { status: call.status });
    }
    if (call.sid && call.sid !== result.sid) {
      call.status = 'unconfirmed';
      return json(res, { status: call.status });
    }
    call.sid = result.sid;
    return json(res, { id, status: call.status });
  } catch {
    call.status = 'provider_error';
    return json(res, { status: call.status });
  }
}

async function webhook(req, res, url, id, isReply) {
  const call = calls.get(id);
  if (!call || req.method !== 'POST') return json(res, {}, 404);
  // The trial proxy can change the URL used for Twilio's signature. Use separate
  // server-signed callback URLs and bind each reply to this call's Twilio SID.
  if (!equals(url.searchParams.get('key'), webhookKey(url.pathname))) return json(res, {}, 403);
  let body = '';
  for await (const chunk of req) {
    body += chunk;
    if (body.length > 8192) return json(res, {}, 413);
  }
  const fields = new URLSearchParams(body);
  const sid = fields.get('CallSid');
  if (fields.get('AccountSid') !== config.account || fields.get('To') !== config.to
    || (isReply && !call.sid)
    || !/^CA[\da-f]{32}$/i.test(sid ?? '') || (call.sid && call.sid !== sid)) return json(res, {}, 403);
  call.sid = sid;

  let twiml = '<Hangup/>';
  if (state(call) === 'pending') {
    if (isReply) {
      const digit = fields.get('Digits');
      call.status = digit === '1' ? 'yes' : digit === '2' ? 'no' : 'unconfirmed';
    } else {
      twiml = '<Gather input="dtmf" numDigits="1" timeout="8" actionOnEmptyResult="true"'
        + ' method="POST" action="' + webhookUrl('/reply/' + id) + '">'
        + '<Say language="hi-IN" voice="Polly.Aditi">' + prompt + '</Say></Gather><Hangup/>';
    }
  }
  res.writeHead(200, { 'Content-Type': 'text/xml; charset=utf-8', 'Cache-Control': 'no-store' });
  res.end('<Response>' + twiml + '</Response>');
}

createServer(async (req, res) => {
  try {
    const url = new URL(req.url, relay.relayUrl);
    const match = url.pathname.match(/^\/(call|twiml|reply)\/([\da-f-]{36})$/i);
    if (match && match[1] !== 'call') return await webhook(req, res, url, match[2], match[1] === 'reply');
    if (!equals(req.headers.authorization, 'Bearer ' + relay.relayToken)) return json(res, {}, 404);
    if (url.pathname === '/health' && req.method === 'GET') return json(res, { status: 'ready' });
    if (url.pathname === '/call' && req.method === 'POST') return await dial(res);
    if (match && req.method === 'GET') return json(res, { status: state(calls.get(match[2])) });
    return json(res, {}, 404);
  } catch {
    if (!res.headersSent) json(res, {}, 500);
  }
}).listen(Number(process.env.REFERRAL_VOICE_RELAY_PORT || 4189), '127.0.0.1', () => console.log('Twilio Voice relay listening locally.'));
