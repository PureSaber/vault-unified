import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import vm from 'node:vm';

const source = readFileSync(new URL('../../browser-extension/background.js', import.meta.url), 'utf8');
const passkeySource = readFileSync(new URL('../../browser-extension/passkey-worker.js', import.meta.url), 'utf8');
const connectSource = readFileSync(new URL('../../browser-extension/connect.js', import.meta.url), 'utf8');
const ownId = 'generated-extension';
const origin = 'https://login.example.invalid';
const event = () => ({ addListener() {} });
function fixture(sites = [origin]) {
  const state = { preferences: { all: false, sites, excluded: [], language: 'en' }, grants: true, tab: { id: 7, active: true, url: origin },
    documentOrigin: origin, apiCalls: [], messages: [], windows: [], afterRequest: null, now: 100_000 };
  const chrome = {
    runtime: { id: ownId, getURL: path => `chrome-extension://${ownId}/${path}`, onMessage: event(), onInstalled: event(), onStartup: event() },
    commands: { onCommand: event() },
    alarms: { onAlarm: event(), create() {}, clear: async () => true },
    storage: { session: { get: async () => ({}), set: async () => {}, remove: async () => {} }, local: {
      get: async () => ({ vaultUnifiedInlinePreferences: structuredClone(state.preferences) }),
      set: async value => { state.preferences = structuredClone(value.vaultUnifiedInlinePreferences); },
    } },
    permissions: { contains: async () => state.grants, getAll: async () => ({ origins: [] }), remove: async () => true, onRemoved: event() },
    tabs: { get: async () => state.tab, query: async () => [], onRemoved: event(), sendMessage: async (tabId, value, target) => {
      state.messages.push(structuredClone({ tabId, value, target })); return { filled: true };
    } },
    windows: { create: async value => { state.windows.push(value); } },
    scripting: { executeScript: async () => [{ result: state.documentOrigin }], getRegisteredContentScripts: async () => [], registerContentScripts: async () => {}, unregisterContentScripts: async () => {} },
  };
  const connection = { connectedRequest: async (path, body) => {
    state.apiCalls.push({ path, body });
    if (state.afterRequest) await state.afterRequest(path, body);
    if (path === '/passkeys/begin') return { status: 'pending', request_id: body.request_id, timeout_ms: 120000 };
    if (path === '/passkeys/status') return { status: 'complete', credential: { generatedPublicResponse: true } };
    if (path === '/passkeys/cancel') return { cancelled: true };
    return path.startsWith('/matches') ? { matches: [{ id: 'entry-one', title: 'Generated account', username: 'generated-user' }] }
      : { username: 'generated-user', password: randomUUID() };
  } };
  // No connection request is pending in these inline-fill journeys.
  const identity = { readPending: async () => null, removePending: async () => {} };
  const worker = vm.runInNewContext(`${passkeySource}\n${connectSource}\n${source}\n;({ handle, preferences });`, { chrome, URL, crypto: { randomUUID }, importScripts() {},
    vaultBrowserConnection: connection, vaultBrowserIdentity: identity, setTimeout, clearTimeout, Date: { now: () => state.now } });
  const sender = { id: ownId, tab: { id: 7 }, frameId: 0, documentId: 'document-one', documentLifecycle: 'active', origin, url: `${origin}/login` };
  const select = { type: 'vault-inline-select', mode: 'password', entryId: 'entry-one', nonce: randomUUID() };
  const popup = { id: ownId, url: `chrome-extension://${ownId}/popup.html` };
  const confirm = { id: ownId, url: `chrome-extension://${ownId}/frame-confirm.html` };
  return { state, worker, sender, select, popup, confirm };
}
const rejects = (promise, key) => assert.rejects(promise, error => error.key === key);

test('disabled websites and ungranted origins never query the vault', async () => {
  const { worker, state, sender, select } = fixture([]);
  await rejects(worker.handle(select, sender), 'siteDisabled');
  state.preferences.sites = [origin]; state.grants = false;
  await rejects(worker.handle(select, sender), 'siteDisabled');
  assert.equal(state.apiCalls.length, 0);
});
test('sender identity, active document and exact origin including port are checked', async () => {
  const { worker, state, sender, select } = fixture();
  for (const change of [{ id: 'other-extension' }, { documentLifecycle: 'prerender' }, { origin: 'null' }, { url: 'https://user:pass@login.example.invalid' }, { documentId: undefined }]) {
    await rejects(worker.handle(select, { ...sender, ...change }), 'pageChanged');
  }
  const other = `${origin}:8443`;
  await rejects(worker.handle(select, { ...sender, url: other, origin: other }), 'siteDisabled');
  assert.equal(state.apiCalls.length, 0);
});
test('delivery targets only the initiating document and requested field', async () => {
  const { worker, state, sender, select } = fixture();
  assert.equal((await worker.handle(select, sender)).filled, true);
  assert.equal(state.apiCalls[0].body.field, 'password');
  assert.equal(state.messages[0].target.documentId, sender.documentId);
  assert.equal(state.messages[0].value.nonce, select.nonce);
});
test('navigation, tab changes and revoked permission during a request stop delivery', async () => {
  for (const mutate of [state => { state.documentOrigin = 'https://other.invalid'; }, state => { state.tab.active = false; },
    state => { state.grants = false; }, state => { state.tab.url = 'https://other.invalid'; }]) {
    const { worker, state, sender, select } = fixture();
    state.afterRequest = () => mutate(state);
    await rejects(worker.handle(select, sender), 'pageChanged');
    assert.equal(state.messages.length, 0);
  }
});
test('a cross-origin frame needs extension confirmation; cancellation consumes it', async () => {
  const { worker, state, sender, select, confirm } = fixture();
  state.tab.url = 'https://outer.example.invalid';
  assert.equal((await worker.handle(select, sender)).confirmation, true);
  assert.equal(state.apiCalls.filter(call => call.path === '/fill').length, 0);
  const id = new URL(state.windows[0].url).searchParams.get('id');
  await rejects(worker.handle({ type: 'vault-frame-approve', id }, sender), 'requestError');
  assert.equal((await worker.handle({ type: 'vault-frame-info', id }, confirm)).origin, origin);
  await worker.handle({ type: 'vault-frame-cancel', id }, confirm);
  assert.equal(state.messages[0].value.type, 'vault-inline-cancel');
  assert.equal(state.messages[0].value.nonce, select.nonce);
  await rejects(worker.handle({ type: 'vault-frame-approve', id }, confirm), 'expired');
  assert.equal(state.apiCalls.filter(call => call.path === '/fill').length, 0);
});
test('frame approval is single-use and cannot outlive permission or its timeout', async () => {
  for (const mode of ['approve', 'revoke', 'expire']) {
    const { worker, state, sender, select, confirm } = fixture();
    state.tab.url = 'https://outer.example.invalid';
    await worker.handle(select, sender);
    const id = new URL(state.windows[0].url).searchParams.get('id');
    if (mode === 'revoke') state.grants = false;
    if (mode === 'expire') state.now += 60_001;
    const request = { type: 'vault-frame-approve', id };
    if (mode === 'approve') assert.equal((await worker.handle(request, confirm)).filled, true);
    else await rejects(worker.handle(request, confirm), mode === 'revoke' ? 'pageChanged' : 'expired');
    await rejects(worker.handle(request, confirm), 'expired');
    assert.equal(state.apiCalls.filter(call => call.path === '/fill').length, mode === 'approve' ? 1 : 0);
  }
});
test('malformed preferences cannot broaden site access; simultaneous updates survive', async () => {
  const { worker, state, popup } = fixture([null, 7, 'file:///generated', `${origin}/login`, origin]);
  assert.equal(JSON.stringify((await worker.preferences()).sites), JSON.stringify([origin]));
  await Promise.all(['https://first.invalid', 'https://second.invalid'].map(origin => worker.handle({
    type: 'vault-inline-settings', action: 'enable-site', origin, language: 'en',
  }, popup)));
  assert.equal(state.preferences.sites.length, 3);
});

test('Passkeys are opt-in and cannot select a different page origin', async () => {
  const { worker, state, sender } = fixture();
  const message = { type: 'vault-passkey-begin', id: randomUUID(), operation: 'get', origin: 'https://other.invalid', options: { challenge: 'generated' } };
  assert.equal((await worker.handle(message, sender)).status, 'fallback');
  assert.equal(state.apiCalls.length, 0);
  state.preferences.passkeys = true;
  assert.equal((await worker.handle(message, sender)).status, 'complete');
  assert.equal(state.apiCalls[0].body.origin, origin);
  assert.equal(state.apiCalls.at(-1).path, '/passkeys/cancel');
});

test('Passkey cross-origin frames and ungranted sites never reach the vault', async () => {
  for (const change of [state => state.grants = false, state => state.tab.url = 'https://outer.invalid']) {
    const { worker, state, sender } = fixture(); state.preferences.passkeys = true; change(state);
    assert.equal((await worker.handle({ type: 'vault-passkey-begin', id: randomUUID(), operation: 'create', options: {} }, sender)).status, 'fallback');
    assert.equal(state.apiCalls.length, 0);
  }
});

test('immediate Passkey cancellation wins before asynchronous permission checks', async () => {
  const { worker, state, sender } = fixture(); state.preferences.passkeys = true;
  const id = randomUUID();
  const started = worker.handle({ type: 'vault-passkey-begin', id, operation: 'create', options: {} }, sender);
  await worker.handle({ type: 'vault-passkey-cancel', id }, sender);
  assert.equal((await started).status, 'cancelled');
  assert.equal(state.apiCalls.length, 0);
});

test('navigation and Passkey opt-out before result delivery cancel the approved response', async () => {
  for (const change of [state => state.documentOrigin = 'https://other.invalid', state => state.preferences.passkeys = false]) {
    const { worker, state, sender } = fixture(); state.preferences.passkeys = true;
    state.afterRequest = path => { if (path === '/passkeys/status') change(state); };
    const result = await worker.handle({ type: 'vault-passkey-begin', id: randomUUID(), operation: 'get', options: {} }, sender);
    assert.equal(result.status, 'cancelled');
    assert.equal(result.credential, undefined);
    assert.equal(state.apiCalls.at(-1).path, '/passkeys/cancel');
  }
});

test('Passkey validation rejection falls back, but uncertain begin delivery fails closed', async () => {
  for (const code of [400, 401, undefined]) {
    const { worker, state, sender } = fixture(); state.preferences.passkeys = true;
    state.afterRequest = path => { if (path === '/passkeys/begin') throw Object.assign(new Error('generated rejection'), { code }); };
    const result = await worker.handle({ type: 'vault-passkey-begin', id: randomUUID(), operation: 'create', options: {} }, sender);
    assert.equal(result.status, code ? 'fallback' : 'cancelled');
    assert.equal(state.apiCalls.at(-1).path, '/passkeys/cancel');
  }
});

// First-connection requests (connect.js) run in the same worker.
function connectFixture({ api = {}, located = [{ address: 'http://127.0.0.1:43129', nonce: 'generated-nonce' }], pending = null } = {}) {
  const state = { session: {}, alarms: [], requests: [], saved: null, pending, located: [...located] };
  const chrome = {
    runtime: { id: ownId, getURL: path => `chrome-extension://${ownId}/${path}`, getManifest: () => ({ version: '1.4.0' }), onMessage: event(), onInstalled: event(), onStartup: event() },
    commands: { onCommand: event() },
    alarms: { onAlarm: event(), create: name => { state.alarms.push(`create:${name}`); }, clear: async name => { state.alarms.push(`clear:${name}`); return true; } },
    storage: {
      session: { get: async key => ({ [key]: state.session[key] }), set: async value => { Object.assign(state.session, structuredClone(value)); }, remove: async key => { delete state.session[key]; } },
      local: { get: async () => ({}), set: async () => {} },
    },
    permissions: { contains: async () => false, getAll: async () => ({ origins: [] }), onRemoved: event() },
    tabs: { onRemoved: event() },
  };
  const identity = {
    create: async () => ({ privateKey: { extractable: false, label: 'generated-key' }, publicKey: 'generated-public-key' }),
    savePending: async (value, record) => { state.pending = { privateKey: value.privateKey, publicKey: value.publicKey, ...record }; },
    readPending: async () => state.pending,
    removePending: async () => { state.pending = null; },
    save: async (value, deviceId, sidecarUrl) => { state.saved = { publicKey: value.publicKey, deviceId, sidecarUrl }; },
  };
  const connection = { locate: async () => (state.located.length > 1 ? state.located.shift() : state.located[0]) };
  const fetch = async (url, init) => {
    const path = new URL(url).pathname.replace('/api/browser', '');
    state.requests.push({ path, body: JSON.parse(init.body), headers: init.headers });
    const reply = (await api[path]?.(JSON.parse(init.body), init.headers)) || { status: 500, body: {} };
    return new Response(JSON.stringify(reply.body), { status: reply.status });
  };
  const worker = vm.runInNewContext([passkeySource, connectSource, source, ';({ handle });'].join('\n'), { chrome, URL, crypto: { randomUUID }, importScripts() {},
    vaultBrowserConnection: connection, vaultBrowserIdentity: identity, fetch, Response, AbortSignal, structuredClone,
    navigator: { userAgentData: { brands: [{ brand: 'Chromium' }, { brand: 'Google Chrome' }], platform: 'Windows' } },
    setTimeout: () => 1, clearTimeout() {}, Date });
  const popup = { id: ownId, url: `chrome-extension://${ownId}/popup.html` };
  // Replies are created in the worker's realm; compare plain copies.
  return { state, worker: { handle: (...args) => worker.handle(...args).then(value => JSON.parse(JSON.stringify(value))) }, popup };
}
const settle = () => new Promise(resolve => setImmediate(resolve));
const started = { status: 200, body: { request_id: 'generated-request', poll_secret: 'generated-poll-secret', code: '482913', expires_in_seconds: 120 } };

test('two popups share one connect request that carries the nonce and keeps the key pending', async () => {
  const { worker, state, popup } = connectFixture({ api: { '/connect/request': () => started } });
  const [first, second] = await Promise.all([worker.handle({ type: 'vault-connect-start' }, popup), worker.handle({ type: 'vault-connect-start' }, popup)]);
  assert.deepEqual(first, { state: 'waiting', code: '482913' });
  assert.deepEqual(second, first);
  const requests = state.requests.filter(item => item.path === '/connect/request');
  assert.equal(requests.length, 1);
  assert.equal(requests[0].headers['X-Vault-Connect-Nonce'], 'generated-nonce');
  assert.deepEqual(requests[0].body, { public_key: 'generated-public-key', device_name: 'Google Chrome on Windows' });
  assert.equal(state.pending.requestId, 'generated-request');
  assert.equal(state.pending.privateKey.extractable, false);
  assert.ok(state.alarms.includes('create:vault-connect'));
});

test('a nonce from before a desktop restart is rediscovered once', async () => {
  const located = [{ address: 'http://127.0.0.1:43129', nonce: 'previous-run' }, { address: 'http://127.0.0.1:43130', nonce: 'current-run' }];
  const { worker, state, popup } = connectFixture({ located, api: { '/connect/request': (body, headers) => headers['X-Vault-Connect-Nonce'] === 'current-run' ? started : { status: 403, body: {} } } });
  assert.deepEqual(await worker.handle({ type: 'vault-connect-start' }, popup), { state: 'waiting', code: '482913' });
  assert.deepEqual(state.requests.map(item => item.headers['X-Vault-Connect-Nonce']), ['previous-run', 'current-run']);
  assert.equal(state.pending.sidecarUrl, 'http://127.0.0.1:43130');
});

test('approval saves the identity and pairing address, never a token', async () => {
  const deviceId = 'a'.repeat(32);
  const { worker, state, popup } = connectFixture({ api: { '/connect/request': () => started, '/connect/status': () => ({ status: 200, body: { state: 'approved', device_id: deviceId } }) } });
  await worker.handle({ type: 'vault-connect-start' }, popup);
  assert.deepEqual(await worker.handle({ type: 'vault-connect-state' }, popup), { state: 'approved' });
  assert.deepEqual(state.saved, { publicKey: 'generated-public-key', deviceId, sidecarUrl: 'http://127.0.0.1:43129' });
  assert.deepEqual(state.session.vaultUnifiedBrowserPairing, { deviceId, sidecarUrl: 'http://127.0.0.1:43129' });
  assert.equal(state.pending, null);
  assert.ok(state.alarms.includes('clear:vault-connect'));
  assert.deepEqual(state.requests.at(-1).body, { request_id: 'generated-request', poll_secret: 'generated-poll-secret' });
  assert.deepEqual(await worker.handle({ type: 'vault-connect-ack' }, popup), { state: 'idle' });
  assert.deepEqual(await worker.handle({ type: 'vault-connect-state' }, popup), { state: 'idle' });
});

test('a refusal or an unknown request discards the pending key', async () => {
  for (const [reply, expected] of [[{ status: 200, body: { state: 'denied' } }, 'denied'], [{ status: 404, body: {} }, 'expired']]) {
    const { worker, state, popup } = connectFixture({ api: { '/connect/request': () => started, '/connect/status': () => reply } });
    await worker.handle({ type: 'vault-connect-start' }, popup);
    assert.deepEqual(await worker.handle({ type: 'vault-connect-state' }, popup), { state: expected });
    assert.equal(state.saved, null);
    assert.equal(state.pending, null);
  }
});

test('a restarted worker resumes a request still waiting for approval', async () => {
  const pending = { privateKey: { extractable: false }, publicKey: 'generated-public-key', requestId: 'generated-request', pollSecret: 'generated-poll-secret',
    code: '482913', expiresAt: Date.now() + 60_000, sidecarUrl: 'http://127.0.0.1:43129' };
  const { state } = connectFixture({ pending, api: { '/connect/status': () => ({ status: 200, body: { state: 'pending', remaining_seconds: 60 } }) } });
  for (let i = 0; i < 5; i++) await settle();
  assert.deepEqual(state.requests.map(item => item.path), ['/connect/status']);
  assert.ok(state.pending, 'the pending key is kept while waiting');
});

test('only the extension popup can start or watch a connection', async () => {
  const { worker, state } = connectFixture({ api: { '/connect/request': () => started } });
  const page = { id: ownId, tab: { id: 7 }, frameId: 0, documentId: 'document-one', documentLifecycle: 'active', origin, url: `${origin}/login` };
  for (const type of ['vault-connect-start', 'vault-connect-state', 'vault-connect-cancel']) {
    await rejects(worker.handle({ type }, page), 'requestError');
    await rejects(worker.handle({ type }, { id: ownId, url: `chrome-extension://${ownId}/frame-confirm.html` }), 'expired');
  }
  assert.equal(state.requests.length, 0);
});
