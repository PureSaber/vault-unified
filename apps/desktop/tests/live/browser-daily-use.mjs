import { chromium } from '../../node_modules/playwright/index.mjs';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join, sep, basename } from 'node:path';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';
const root = fileURLToPath(new URL('../../../../', import.meta.url));
const isolated = await mkdtemp(join(tmpdir(), 'vault-browser-live-'));
const bootstrap = randomBytes(32).toString('hex');
const master = randomBytes(32).toString('hex');
const firstPassword = randomBytes(24).toString('hex');
const assert = (condition, message) => { if (!condition) throw new Error(message); };
let context, apiProcess, site;
let step = 'startup';
try {
  apiProcess = spawn(join(root, '.venv/Scripts/python.exe'), ['-m', 'vault_unified.api.app'], {
    cwd: isolated, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, VAULT_API_BOOTSTRAP_SECRET: bootstrap, VAULT_API_PORT: '0',
      VAULT_API_HOST: '127.0.0.1', VAULT_DATA_DIR: isolated, VAULT_FILE: join(isolated, 'test.vault'),
      VAULT_CONFIG_DIR: join(isolated, 'config'), PYTHONUNBUFFERED: '1' },
  });
  apiProcess.stderr.on('data', () => {});
  const ready = await new Promise((accept, reject) => {
    let output = '';
    const timeout = setTimeout(() => reject(new Error('API startup timed out')), 20000);
    apiProcess.stdout.on('data', (chunk) => {
      output += chunk.toString();
      const line = output.split('\n').find((item) => item.startsWith('VAULT_API_READY '));
      if (line) { clearTimeout(timeout); accept(JSON.parse(line.slice(16))); output = ''; }
    });
    apiProcess.once('exit', () => { clearTimeout(timeout); reject(new Error('API exited')); });
  });
  const apiUrl = `http://127.0.0.1:${ready.port}`;
  let token;
  const api = async (path, body, method = 'POST') => {
    const response = await fetch(`${apiUrl}/api${path}`, { method,
      headers: { 'Content-Type': 'application/json', 'X-Vault-Bootstrap': bootstrap,
        'X-Vault-Client': 'vault-unified-desktop', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      ...(method === 'GET' ? {} : { body: JSON.stringify(body || {}) }) });
    assert(response.ok, `API ${path} failed with ${response.status}`);
    return response.json();
  };
  token = (await api('/auth/create', { password: master, confirm_password: master })).token;
  site = createServer((req, res) => {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    if (req.url === '/changed') return res.end('<h1>Generated website accepted the change</h1>');
    if (req.url === '/change') return res.end('<!doctype html><html><title>Generated website</title><form action="/changed" method="post"><input id="user" autocomplete="username"><input id="old" type="password" autocomplete="current-password"><input id="new" type="password" autocomplete="new-password"><input id="confirm" type="password" autocomplete="new-password"><button>Change password</button></form></html>');
    res.end('<!doctype html><html><title>Generated website</title><form><input id="user" autocomplete="username"><input id="password" type="password" autocomplete="current-password"><button>Sign in</button></form></html>');
  });
  await new Promise((accept) => site.listen(0, '127.0.0.1', accept));
  const siteUrl = `http://127.0.0.1:${site.address().port}`;
  context = await chromium.launchPersistentContext(join(isolated, 'profile'), {
    channel: 'chromium', headless: true,
    args: [`--disable-extensions-except=${join(root, 'apps/browser-extension')}`, `--load-extension=${join(root, 'apps/browser-extension')}`],
  });
  const manager = await context.newPage();
  await manager.goto('chrome://extensions');
  const extension = manager.locator('extensions-item').filter({ hasText: 'Vault Unified' });
  await extension.waitFor();
  const extensionId = await extension.getAttribute('id');
  assert(extensionId && /^[a-p]{32}$/.test(extensionId), 'Unpacked extension did not load');
  const website = await context.newPage();
  await website.goto(siteUrl);
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${extensionId}/popup.html`);
  const tabs = await popup.evaluate(() => chrome.tabs.query({}));
  const websiteTab = tabs.find((tab) => tab.url?.startsWith(siteUrl));
  await popup.goto(`chrome-extension://${extensionId}/popup.html?tab=${websiteTab.id}&lang=en`);
  step = 'real extension pairing';
  const pairing = await api('/browser/pairing-code');
  await popup.locator('#sidecar-url').fill(apiUrl);
  await popup.locator('#pairing-code').fill(pairing.pairing_code);
  await popup.locator('#pair-form button').click();
  await popup.locator('#accounts').waitFor();
  step = 'capture and confirmed save';
  await website.locator('#user').fill('generated-user');
  await website.locator('#password').fill(firstPassword);
  await popup.locator('#capture').click();
  await popup.locator('#save-form').waitFor();
  assert(await popup.locator('#save-password').inputValue() === firstPassword, 'Page capture failed');
  await popup.locator('#review').click();
  await popup.locator('#confirmed').check();
  await popup.locator('#confirm-save').click();
  await popup.locator('#accounts').waitFor();
  const entries = await api('/entries', null, 'GET');
  assert(entries.length === 1, 'Expected one saved account');
  step = 'real content script fill';
  await website.locator('#password').fill('');
  await popup.locator('button.match').click();
  await website.waitForFunction(() => document.querySelector('#password').value.length > 0);
  assert(await website.locator('#password').inputValue() === firstPassword, 'Saved account was not filled');
  step = 'password change across website interaction';
  await website.goto(siteUrl + '/change');
  await website.locator('#old').fill(firstPassword);
  await popup.locator('button.update').click();
  await popup.locator('#generate').click();
  await popup.waitForFunction(() => document.querySelector('#save-password').value.length > 0);
  const changedPassword = await popup.locator('#save-password').inputValue();
  await popup.locator('#fill-new').click();
  await website.waitForFunction(() => document.querySelector('#new').value.length > 0);
  assert(await website.locator('#old').inputValue() === firstPassword, 'Current password changed while filling new password');
  assert(await website.locator('#new').inputValue() === changedPassword, 'Generated password not filled');
  assert(await website.locator('#confirm').inputValue() === changedPassword, 'Confirmation field not filled');
  await website.getByRole('button', { name: 'Change password' }).click();
  await website.waitForURL(siteUrl + '/changed');
  assert(await popup.locator('#save-password').inputValue() === changedPassword, 'Standalone draft lost after visiting website');
  await popup.locator('#review').click();
  await popup.locator('#confirmed').check();
  await popup.locator('#confirm-save').click();
  await popup.locator('#accounts').waitFor();
  const updated = await api(`/entries/${entries[0].id}?reveal=true`, null, 'GET');
  assert(updated.password === changedPassword && updated.history_count === 1, 'Password update/history failed');
  step = 'lock and reconnect';
  await api('/auth/lock');
  await popup.locator('#retry').waitFor();
  assert(await popup.locator('#save-password').inputValue() === '', 'Locked draft was retained');
  token = (await api('/auth/unlock', { password: master })).token;
  await popup.locator('#retry').click();
  await popup.locator('#accounts').waitFor();
  assert(await popup.locator('#pair-form').isHidden(), 'Unlock required pairing again');
  const stored = await popup.evaluate(() => chrome.storage.session.get(null));
  const serialized = JSON.stringify(stored);
  assert(!serialized.includes(firstPassword) && !serialized.includes(changedPassword), 'A password entered extension storage');
  step = 'revocation';
  await popup.locator('#forget').click();
  await popup.locator('#pair-form').waitFor();
  console.log(JSON.stringify({ result: 'passed', actual_chromium_extension: true, actual_isolated_api: true,
    flows: ['pair', 'capture-save', 'fill', 'generate-change-update-history', 'lock-resume', 'forget'],
    real_credentials_used: false }));
} catch (error) {
  console.error(`Generated-data live browser check failed at: ${step}; ${String(error.message).split("\n")[0]}`);
  process.exitCode = 1;
} finally {
  if (context) await context.close();
  if (site) await new Promise((accept) => site.close(accept));
  if (apiProcess && apiProcess.exitCode === null) {
    apiProcess.kill();
    await new Promise((accept) => { const timer = setTimeout(accept, 5000); apiProcess.once('exit', () => { clearTimeout(timer); accept(); }); });
  }
  const allowedRoot = resolve(tmpdir()) + sep;
  if (resolve(isolated).startsWith(allowedRoot) && basename(isolated).startsWith('vault-browser-live-')) {
    await rm(isolated, { recursive: true, force: true, maxRetries: 3 });
  }
}
