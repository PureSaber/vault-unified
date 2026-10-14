import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import vm from 'node:vm';

const source = readFileSync(new URL('../../browser-extension/background.js', import.meta.url), 'utf8');
const passkeySource = readFileSync(new URL('../../browser-extension/passkey-worker.js', import.meta.url), 'utf8');
const ownId = 'generated-extension';
const origin = 'https://login.example.invalid';
const event = () => ({ addListener() {} });
function fixture(sites = [origin]) {
  const state = { preferences: { all: false, sites, excluded: [], language: 'en' }, grants: true, tab: { id: 7, active: true, url: origin },
    documentOrigin: origin, apiCalls: [], messages: [], windows: [], afterRequest: null, now: 100_000 };
  const chrome = {
    runtime: { id: ownId, getURL: path => `chrome-extension://${ownId}/${path}`, onMessage: event(), onInstalled: event(), onStartup: event() },
    commands: { onCommand: event() },
    storage: { local: {
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
  const worker = vm.runInNewContext(`${passkeySource}\n${source}\n;({ handle, preferences });`, { chrome, URL, crypto: { randomUUID }, importScripts() {},
    vaultBrowserConnection: connection, Date: { now: () => state.now } });
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
