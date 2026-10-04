import { chromium } from '../../node_modules/playwright/index.mjs';
import { spawn, execFileSync } from 'node:child_process';
import { createServer } from 'node:http';
import { cp, mkdtemp, readFile, writeFile, rename, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join, dirname, basename } from 'node:path';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../../../../', import.meta.url));
const isolated = await mkdtemp(join(tmpdir(), 'vault-trust-live-'));
const python = join(root, '.venv/Scripts/python.exe');
const executable = join(root, 'apps/desktop/src-tauri/target/debug/vault-unified-desktop.exe');
const fixture = join(root, 'tests/helpers/browser_bridge_fixture.py');
const host = `org.vaultunified.test_${randomBytes(8).toString('hex')}`;
const bootstrap = randomBytes(32).toString('hex');
const master = randomBytes(32).toString('hex');
const password = randomBytes(24).toString('hex');
const assert = (condition, message) => { if (!condition) throw new Error(message); };
let context, processHandle, site, apiUrl, token, step = 'startup';
const delay = (ms) => new Promise((accept) => setTimeout(accept, ms));

async function startApi() {
  processHandle = spawn(python, ['-m', 'vault_unified.api.app'], { cwd: isolated, windowsHide: true,
    stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, VAULT_API_BOOTSTRAP_SECRET: bootstrap,
      VAULT_API_PORT: '0', VAULT_API_HOST: '127.0.0.1', VAULT_DATA_DIR: isolated,
      VAULT_FILE: join(isolated, 'generated.vault'), VAULT_CONFIG_DIR: join(isolated, 'config'),
      VAULT_BROWSER_DISCOVERY_DIR: join(isolated, 'bridge'), VAULT_BROWSER_HOST_EXE: '', PYTHONUNBUFFERED: '1' } });
  processHandle.stderr.on('data', () => {});
  const ready = await new Promise((accept, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error('API startup timeout')), 20000);
    processHandle.stdout.on('data', (chunk) => {
      output += chunk.toString();
      const line = output.split('\n').find((item) => item.startsWith('VAULT_API_READY '));
      if (line) { clearTimeout(timer); output = ''; accept(JSON.parse(line.slice(16))); }
    });
    processHandle.once('exit', () => { clearTimeout(timer); reject(new Error('API exited')); });
  });
  apiUrl = `http://127.0.0.1:${ready.port}`;
  for (let i = 0; i < 50; i++) {
    try { if ((await fetch(`${apiUrl}/api/browser/discovery`)).ok) return ready; } catch { /* starting */ }
    await delay(100);
  }
  throw new Error('API did not start accepting requests');
}
async function stopApi() {
  if (!processHandle || processHandle.exitCode !== null) return;
  const stopped = new Promise((accept) => processHandle.once('exit', accept));
  processHandle.kill();
  await stopped;
}
async function api(path, body, method = 'POST') {
  const response = await fetch(`${apiUrl}/api${path}`, { method,
    headers: { 'Content-Type': 'application/json', 'X-Vault-Bootstrap': bootstrap, 'X-Vault-Client': 'vault-unified-desktop',
      ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    ...(method === 'GET' ? {} : { body: JSON.stringify(body || {}) }) });
  assert(response.ok, `API ${path} failed with ${response.status}`);
  return response.json();
}
async function launch() {
  context = await chromium.launchPersistentContext(join(isolated, 'profile'), {
    channel: 'chromium', headless: true, env: { ...process.env, VAULT_BROWSER_DISCOVERY_DIR: join(isolated, 'bridge') },
    args: [`--disable-extensions-except=${join(isolated, 'extension')}`, `--load-extension=${join(isolated, 'extension')}`],
  });
  const manager = await context.newPage();
  await manager.goto('chrome://extensions');
  const item = manager.locator('extensions-item').filter({ hasText: 'Vault Unified' });
  await item.waitFor();
  const id = await item.getAttribute('id');
  assert(/^[a-p]{32}$/.test(id), 'Extension did not load');
  const website = await context.newPage();
  const siteUrl = `http://127.0.0.1:${site.address().port}`;
  await website.goto(siteUrl);
  const popup = await context.newPage();
  await popup.goto(`chrome-extension://${id}/popup.html`);
  const tabs = await popup.evaluate(() => chrome.tabs.query({}));
  const tab = tabs.find((value) => value.url?.startsWith(siteUrl));
  await popup.goto(`chrome-extension://${id}/popup.html?tab=${tab.id}&lang=en`);
  return { id, popup, website, siteUrl };
}

try {
  await cp(join(root, 'apps/browser-extension'), join(isolated, 'extension'), { recursive: true });
  // Only the native host name changes, so this test never registers/replaces
  // production Chrome/Edge host keys or uses the owner's browser profile.
  const popupPath = join(isolated, 'extension/popup.js');
  await writeFile(popupPath, (await readFile(popupPath, 'utf8')).replace('org.vaultunified.desktop', host));
  site = createServer((_req, response) => response.end('<!doctype html><input autocomplete="username"><input type="password" autocomplete="current-password">'));
  await new Promise((accept) => site.listen(0, '127.0.0.1', accept));
  const first = await startApi();
  token = (await api('/auth/create', { password: master, confirm_password: master })).token;
  let browser = await launch();
  execFileSync(python, [fixture, 'register', isolated, host, executable, `chrome-extension://${browser.id}/`], { cwd: root, windowsHide: true, stdio: 'pipe' });
  step = 'native discovery and persistent enrollment';
  const discovered = await browser.popup.evaluate((name) => chrome.runtime.sendNativeMessage(name, { type: 'discover', protocol: 1 }), host);
  assert(Object.keys(discovered).sort().join() === 'base_url,instance_id,protocol', 'Discovery returned unexpected fields');
  assert(discovered.instance_id === first.instance_id, 'Native host did not find the running API');
  await api('/entries', { title: 'Generated restart account', username: 'generated-user', password, url: browser.siteUrl });
  const pairing = await api('/browser/pairing-code');
  await browser.popup.locator('#sidecar-url').fill(apiUrl);
  await browser.popup.locator('#pairing-code').fill(pairing.pairing_code);
  await browser.popup.locator('#device-name').fill('Generated restart browser');
  await browser.popup.locator('#pair-form button').click();
  await browser.popup.locator('#accounts').waitFor();
  const identityCheck = await browser.popup.evaluate(async () => {
    const identity = await vaultBrowserIdentity.read();
    let exportDenied = false;
    try { await crypto.subtle.exportKey('pkcs8', identity.privateKey); } catch { exportDenied = true; }
    return { keys: Object.keys(identity).sort(), exportDenied, deviceId: identity.deviceId };
  });
  assert(identityCheck.exportDenied, 'Browser private key was extractable');
  assert(identityCheck.keys.join() === 'deviceId,privateKey,publicKey,sidecarUrl', 'Unexpected persistent identity contents');
  await context.close(); context = null;
  await stopApi();
  const nativeRequest = Buffer.from(JSON.stringify({ type: 'discover', protocol: 1 }));
  const prefix = Buffer.alloc(4); prefix.writeUInt32LE(nativeRequest.length);
  const stale = execFileSync(executable, [`chrome-extension://${browser.id}/`], {
    windowsHide: true, input: Buffer.concat([prefix, nativeRequest]), timeout: 5000,
    env: { ...process.env, VAULT_BROWSER_DISCOVERY_DIR: join(isolated, 'bridge') },
  });
  assert(stale.readUInt32LE(0) === stale.length - 4 && JSON.parse(stale.subarray(4).toString()).error === 'desktop-unavailable', 'Native host accepted a stopped API instance');
  step = 'restart both processes with changed port and locked vault';
  const second = await startApi();
  assert(second.instance_id !== first.instance_id, 'API instance did not restart');
  assert(second.port !== first.port, 'Fixture needs a new port to prove discovery');
  browser = await launch();
  await browser.popup.locator('#retry').waitFor();
  assert(await browser.popup.locator('#accounts').isHidden(), 'Locked vault exposed accounts after restart');
  token = (await api('/auth/unlock', { password: master })).token;
  await browser.popup.locator('#retry').click();
  await browser.popup.locator('#accounts').waitFor();
  assert(await browser.popup.locator('#pair-form').isHidden(), 'Restart required a new pairing code');
  await browser.popup.locator('button.match').click();
  await browser.website.waitForFunction(() => document.querySelector('[type=password]').value.length > 0);
  assert(await browser.website.locator('[type=password]').inputValue() === password, 'Restarted browser failed real filling');
  step = 'manual address fallback when native discovery is unavailable';
  const manifest = join(isolated, 'bridge/native-host.json');
  const disabledManifest = join(isolated, 'bridge/native-host.disabled.json');
  await rename(manifest, disabledManifest);
  try {
    await browser.popup.evaluate(async (oldAddress) => {
      const value = (await chrome.storage.session.get('vaultUnifiedBrowserPairing')).vaultUnifiedBrowserPairing;
      value.sidecarUrl = oldAddress;
      delete value.browserToken;
      await chrome.storage.session.set({ vaultUnifiedBrowserPairing: value });
    }, `http://127.0.0.1:${first.port}`);
    await browser.popup.reload();
    await browser.popup.locator('#retry-address-form').waitFor();
    await browser.popup.locator('#retry-address').fill(apiUrl);
    await browser.popup.locator('#retry-address-form button').click();
    await browser.popup.locator('#accounts').waitFor();
    assert(await browser.popup.locator('#pair-form').isHidden(), 'Manual address fallback required new authorization');
  } finally { await rename(disabledManifest, manifest); }
  const persistent = await browser.popup.evaluate(async () => ({ local: await chrome.storage.local.get(null), sync: await chrome.storage.sync.get(null) }));
  assert(JSON.stringify(persistent) === '{"local":{},"sync":{}}', 'Extension wrote persistent browser token storage');
  const devices = await api('/browser/devices', null, 'GET');
  assert(devices.devices.length === 1 && devices.devices[0].id === identityCheck.deviceId, 'Device list lost authorization across restart');
  step = 'desktop revocation rejects outstanding browser authorization';
  await api(`/browser/devices/${identityCheck.deviceId}`, {}, 'DELETE');
  await browser.popup.evaluate(() => chrome.storage.session.clear());
  await browser.popup.reload();
  await browser.popup.locator('#pair-form').waitFor();
  assert(await browser.popup.locator('#accounts').isHidden(), 'Revoked browser regained access');
  assert((await api('/browser/devices', null, 'GET')).devices.length === 0, 'Revoked device remained listed');
  console.log(JSON.stringify({ result: 'passed', actual_native_executable: true, actual_windows_credentials: true,
    actual_chromium_extension: true, actual_api_restart: true, changed_port_discovered: true,
    private_key_export_denied: true, stale_instance_rejected: true, locked_access_denied: true, manual_address_fallback: true,
    desktop_revocation: true, real_credentials_used: false }));
} catch (error) {
  console.error(`Generated trust restart check failed at ${step}: ${String(error.message).split('\n')[0]}`);
  process.exitCode = 1;
} finally {
  if (context) await context.close();
  await stopApi();
  if (site) await new Promise((accept) => site.close(accept));
  try { execFileSync(python, [fixture, 'clean', isolated, host], { cwd: root, windowsHide: true, stdio: 'pipe' }); }
  catch { console.error('Generated fixture cleanup failed; isolated artifacts retained'); process.exitCode = 1; }
  const target = resolve(isolated);
  if (process.exitCode !== 1 && dirname(target) === resolve(tmpdir()) && basename(target).startsWith('vault-trust-live-')) {
    await rm(target, { recursive: true, force: true });
  }
}
