// Run only on a disposable Windows CI worker, against an actually installed EXE.
import { chromium } from '../../node_modules/playwright/index.mjs';
import { spawn, execFileSync } from 'node:child_process';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { createServer } from 'node:net';
import { randomBytes } from 'node:crypto';
import { resolve, join, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { installedBrowsers } from './installed-browser-journey.mjs';

const [executable, data, mode, expectedVersion, browserPhase] = process.argv.slice(2);
const root = fileURLToPath(new URL('../../../../', import.meta.url));
const assert = (value, message) => { if (!value) throw new Error(message); };
assert(process.env.GITHUB_ACTIONS === 'true' && process.env.RUNNER_TEMP, 'Installed lifecycle requires a disposable CI worker');
assert(resolve(data).startsWith(resolve(process.env.RUNNER_TEMP) + sep), 'Generated data must stay inside runner temporary storage');
assert(['seed', 'reopen'].includes(mode), 'Unknown installed journey');
await mkdir(data, { recursive: true });
const fixturePath = join(data, 'generated-fixture.json');
const fixture = mode === 'seed' ? { master: randomBytes(32).toString('hex'), entry: { title: 'Generated installed upgrade account', username: 'generated-user', password: randomBytes(24).toString('hex'), notes: 'Generated upgrade 中文 notes', url: 'https://example.invalid', tags: ['generated-upgrade'] } } : JSON.parse(await readFile(fixturePath, 'utf8'));
const socket = createServer(); await new Promise(done => socket.listen(0, '127.0.0.1', done));
const port = socket.address().port; await new Promise(done => socket.close(done));
const child = spawn(executable, [], { windowsHide: true, stdio: 'ignore', env: { ...process.env,
  VAULT_DATA_DIR: data, VAULT_FILE: join(data, 'generated.vault'), VAULT_CONFIG_DIR: join(data, 'config'),
  VAULT_BROWSER_DISCOVERY_DIR: join(data, 'bridge'), WEBVIEW2_USER_DATA_FOLDER: join(data, 'webview'),
  VAULT_API_SIDECAR: '', WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS: `--remote-debugging-port=${port}` } });
let browser;
const delay = ms => new Promise(done => setTimeout(done, ms));
let stage = 'launch';
try {
  const deadline = Date.now() + 60000;
  let ready = false;
  while (Date.now() < deadline) {
    assert(child.exitCode === null, 'Installed app exited before readiness');
    try { if ((await fetch(`http://127.0.0.1:${port}/json/version`)).ok) { ready = true; break; } } catch { /* starting */ }
    await delay(250);
  }
  assert(ready, 'Installed WebView did not become ready');
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  let page;
  while (Date.now() < deadline) {
    page = browser.contexts().flatMap(context => context.pages())[0];
    if (page) break;
    await delay(100);
  }
  assert(page, 'Installed WebView did not create its page');
  page.setDefaultTimeout(30000);
  await page.waitForFunction(() => Boolean(window.__TAURI_INTERNALS__));
  assert(await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('plugin:app|version')) === expectedVersion, 'Installed version differs from installer');
  await page.evaluate(() => localStorage.setItem('vault_locale', 'en')); await page.reload();
  await page.getByLabel('Master password', { exact: true }).waitFor();
  const runtime = await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('get_api_runtime_config'));
  let token;
  async function api(path, body, method = 'POST', extraHeaders = {}) {
    const response = await fetch(`${runtime.base_url}${path}`, { method, headers: { 'Content-Type': 'application/json', 'X-Vault-Client': 'vault-unified-desktop', 'X-Vault-Bootstrap': runtime.bootstrap_secret, ...(token ? { Authorization: `Bearer ${token}` } : {}), ...extraHeaders }, ...(method === 'GET' ? {} : { body: JSON.stringify(body || {}) }) });
    assert(response.ok, `Installed API ${path} returned ${response.status}`);
    return response.json();
  }
  stage = mode;
  if (mode === 'seed') {
    token = (await api('/auth/create', { password: fixture.master, confirm_password: fixture.master })).token;
    fixture.id = (await api('/entries', fixture.entry)).id;
    fixture.backup = (await api('/backups/create')).created.path;
    await writeFile(fixturePath, JSON.stringify(fixture));
    await api('/auth/lock'); token = null;
    await page.reload();
  } else {
    token = (await api('/auth/unlock', { password: fixture.master })).token;
    const restored = await api(`/entries/${fixture.id}?reveal=true`, null, 'GET');
    for (const field of ['title', 'username', 'password', 'url', 'notes']) assert(restored[field] === fixture.entry[field], `Upgrade changed ${field}`);
    assert(restored.tags.includes('generated-upgrade'), 'Upgrade lost tags');
    assert((await readFile(fixture.backup)).length > 0, 'Upgrade lost encrypted backup');
    const format = await api('/personal/format', null, 'GET');
    if (format.version < format.current_version) {
      const before = await readFile(join(data, 'generated.vault'));
      const cancelled = await api('/personal/format/preview');
      await api('/personal/format/cancel', { preview_token: cancelled.preview_token });
      assert(before.equals(await readFile(join(data, 'generated.vault'))), 'Cancelled migration wrote data');
      const preview = await api('/personal/format/preview');
      const upgraded = await api('/personal/format/apply', { preview_token: preview.preview_token, confirm_upgrade: true });
      assert(before.equals(await readFile(upgraded.backup_path)), 'Migration did not preserve old-format backup');
      token = (await api('/auth/unlock', { password: fixture.master })).token;
    }
    const restoredAfter = await api(`/entries/${fixture.id}?reveal=true`, null, 'GET');
    assert(restoredAfter.password === fixture.entry.password && restoredAfter.notes === fixture.entry.notes, 'Migration lost data');
    if (browserPhase !== 'restart') {
      const pairing = await api('/browser/pairing-code');
      const paired = await api('/browser/pair', { remember_connection: false }, 'POST', { Origin: 'chrome-extension://abcdefghijklmnopabcdefghijklmnop', 'X-Vault-Browser-Pairing': pairing.pairing_code, 'X-Vault-Extension-Version': expectedVersion });
      assert(paired.discovery_available === true, 'Installed app did not register browser bridge');
    }
    const manifest = JSON.parse(await readFile(join(data, 'bridge/native-host.json'), 'utf8'));
    assert(resolve(manifest.path).toLowerCase() === resolve(executable).toLowerCase(), 'Bridge targets a different executable');
  }
  stage = 'renderer unlock';
  // Setup requests used a separate desktop session. Close it before the real
  // UI unlock so browser requests belong to the session displaying approvals.
  if (token) await api('/auth/lock');
  const unlocked = page.waitForResponse(response => response.url().endsWith('/auth/unlock') && response.request().method() === 'POST');
  await page.getByLabel('Master password', { exact: true }).fill(fixture.master);
  await page.getByRole('button', { name: 'Unlock', exact: true }).click();
  token = (await (await unlocked).json()).token;
  await page.getByRole('button', { name: `Open ${fixture.entry.title}`, exact: true }).waitFor();
  if (browserPhase) {
    stage = 'packaged Chrome and Edge flows';
    const extension = join(data, 'extension');
    if (browserPhase === 'initial') {
      execFileSync(join(root, '.venv/Scripts/python.exe'), ['-c', 'import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])', join(root, `Vault-Unified-Browser-Extension-v${expectedVersion}.zip`), extension], { windowsHide: true, stdio: 'ignore' });
    }
    await installedBrowsers({ root, data, desktop: page, api, runtime, master: fixture.master, extension, phase: browserPhase });
  }
  await page.getByRole('button', { name: 'Lock now', exact: true }).click();
  await page.getByLabel('Master password', { exact: true }).waitFor();
  await browser.close(); browser = null;
  console.log(JSON.stringify({ installedVersion: expectedVersion, journey: mode, preservedVault: true, locked: true }));
} catch (error) {
  // Never print response objects, generated credentials or renderer contents.
  const message = String(error.message).split('\n')[0].replaceAll(fixture.master, '[generated]').replaceAll(fixture.entry.password, '[generated]');
  throw new Error(`Installed journey failed at ${stage}: ${error.name}: ${message}`);
} finally {
  await browser?.close().catch(() => {});
  if (child.exitCode === null) { try { execFileSync('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' }); } catch { /* exited */ } }
}
