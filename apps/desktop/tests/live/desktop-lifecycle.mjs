import { chromium } from '../../node_modules/playwright/index.mjs';
import { spawn, execFileSync } from 'node:child_process';
import { cp, mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, basename, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomBytes } from 'node:crypto';
import { exerciseAutoType } from './auto-type-journey.mjs';

const root = fileURLToPath(new URL('../../../../', import.meta.url));
const isolated = await mkdtemp(join(tmpdir(), 'vault-desktop-generated-'));
const executable = join(isolated, 'vault-generated.exe');
const master = randomBytes(32).toString('hex');
const password = randomBytes(24).toString('hex');
let child, browser, page, startupErrors = '', step = 'startup';
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const delay = ms => new Promise(accept => setTimeout(accept, ms));
const wait = async (predicate, timeout = 10_000) => { const deadline = Date.now() + timeout; while (Date.now() < deadline) { if (await predicate()) return; await delay(100); } throw new Error('Condition timed out'); };
const env = { ...process.env, VAULT_DATA_DIR: isolated, VAULT_CONFIG_DIR: join(isolated, 'config'), VAULT_FILE: join(isolated, 'generated.vault'), VAULT_BROWSER_DISCOVERY_DIR: join(isolated, 'bridge'), VAULT_API_SIDECAR: '', WEBVIEW2_USER_DATA_FOLDER: join(isolated, 'webview') };
const native = action => JSON.parse(execFileSync('powershell.exe', ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', join(root, 'apps/desktop/tests/live/native-window.ps1'), '-TargetProcessId', String(child.pid), '-Action', action], { windowsHide: true, encoding: 'utf8' }));
async function start() {
  const reservation = createServer(); await new Promise(accept => reservation.listen(0, '127.0.0.1', accept));
  const port = reservation.address().port; await new Promise(accept => reservation.close(accept));
  env.WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = `--remote-debugging-port=${port}`;
  startupErrors = '';
  child = spawn(executable, [], { cwd: root, env, windowsHide: true, stdio: ['ignore', 'ignore', 'pipe'] });
  child.stderr.on('data', chunk => {
    const safe = chunk.toString().split('\n').filter(line => !/secret|token|VAULT_API_READY/i.test(line)).join('\n');
    startupErrors = (startupErrors + safe).slice(-1800);
  });
  await wait(async () => {
    if (child.exitCode !== null) throw new Error(`Native startup exited (${child.exitCode}): ${startupErrors}`);
    try { return (await fetch(`http://127.0.0.1:${port}/json/version`)).ok; } catch { return false; }
  }, 45_000).catch(error => { throw new Error(`${error.message}; native exit=${child.exitCode}; ${startupErrors}`); });
  browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  await wait(() => browser.contexts().some(context => context.pages().length));
  page = browser.contexts()[0].pages()[0]; page.setDefaultTimeout(15_000);
  await page.waitForFunction(() => Boolean(window.__TAURI_INTERNALS__));
  assert(await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('plugin:app|identifier')) === 'com.puresaber.vault-unified.generated-test', 'Native fixture must use its isolated application identifier');
  await page.evaluate(() => localStorage.setItem('vault_locale', 'en')); await page.reload();
  await page.getByLabel('Master password', { exact: true }).waitFor();
}
try {
  await cp(join(root, 'apps/desktop/src-tauri/target/debug/vault-unified-desktop.exe'), executable);
  await mkdir(join(isolated, 'config'));
  await writeFile(join(isolated, 'config/desktop-preferences.json'), JSON.stringify({ close_to_tray: true, shortcut: 'Control+Shift+Space', locale: 'en' }));
  await start();
  step = 'create and search';
  await page.getByLabel('Master password', { exact: true }).fill(master);
  await page.getByLabel('Confirm master password', { exact: true }).fill(master);
  await page.getByRole('button', { name: 'Create and unlock', exact: true }).click();
  await page.getByRole('button', { name: 'Add password', exact: true }).click();
  await page.getByLabel('Website or app name', { exact: true }).fill('Generated native account');
  const username = 'generated{ENTER}中文';
  await page.getByLabel('Username', { exact: true }).fill(username);
  await page.getByLabel('Password', { exact: true }).fill(password);
  await page.getByRole('button', { name: 'More options', exact: true }).click();
  await page.getByLabel('Choose authenticator QR image', { exact: true }).setInputFiles(join(root, 'apps/desktop/tests/ui/fixtures/totp-rfc-test.png'));
  await page.getByText('QR code loaded into the draft; save to keep it', { exact: true }).waitFor();
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await page.getByRole('button', { name: 'Open Generated native account', exact: true }).waitFor();
  step = 'native Windows session and suspend notifications';
  const runtime = await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('get_api_runtime_config'));
  assert(Object.keys(runtime).sort().join(',') === 'base_url,bootstrap_secret,instance_id', 'Renderer must not receive native capability');
  const hello = await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('windows_hello_status'));
  assert(typeof hello.supported === 'boolean' && !hello.ready && !hello.busy, 'Hello probe must not enroll or unlock');
  await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('disable_windows_hello'));
  const apiHeaders = { 'Content-Type': 'application/json', 'X-Vault-Bootstrap': runtime.bootstrap_secret, 'X-Vault-Client': 'vault-unified-desktop' };
  assert((await fetch(`${runtime.base_url}/auth/hello/prepare`, { method: 'POST', headers: apiHeaders, body: '{}' })).status === 403, 'Renderer bootstrap cannot authorize Hello enrollment');
  const unlockRequest = () => fetch(`${runtime.base_url}/auth/unlock`, { method: 'POST', headers: apiHeaders, body: JSON.stringify({ password: master }) });
  const extraToken = (await (await unlockRequest()).json()).token;
  step = 'native application auto-type';
  const entries = await (await fetch(`${runtime.base_url}/entries`, { headers: { ...apiHeaders, Authorization: `Bearer ${extraToken}` } })).json();
  await exerciseAutoType({ page, root, entryId: entries[0].id, username, password, token: extraToken, focusMain: async () => {
    native('shortcut');
    await page.getByRole('dialog', { name: 'Quick search', exact: true }).getByRole('button', { name: 'Close', exact: true }).click();
  } });
  step = 'native Windows session and suspend notifications';
  await page.getByRole('button', { name: 'Add password', exact: true }).click();
  await page.getByLabel('Website or app name', { exact: true }).fill('Generated draft cleared by Windows lock');
  native('session-lock');
  await page.getByLabel('Master password', { exact: true }).waitFor();
  await wait(async () => !(await (await fetch(`${runtime.base_url}/auth/status`, { headers: { ...apiHeaders, Authorization: `Bearer ${extraToken}` } })).json()).unlocked);
  assert((await unlockRequest()).status === 423, 'Windows lock must block a new password unlock');
  native('suspend'); native('session-unlock');
  assert((await unlockRequest()).status === 423, 'Session unlock must not bypass an outstanding suspend');
  native('resume');
  await wait(async () => (await unlockRequest()).ok);
  assert(await page.getByLabel('Master password', { exact: true }).isVisible(), 'Windows resume must not unlock the user interface');
  await page.getByLabel('Master password', { exact: true }).fill(master);
  await page.getByRole('button', { name: 'Unlock', exact: true }).click();
  await page.getByRole('button', { name: 'Open Generated native account', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Quick search', exact: true }).click();
  const dialog = () => page.getByRole('dialog', { name: 'Quick search', exact: true });
  await dialog().getByRole('option').waitFor();
  await dialog().getByRole('button', { name: 'Close', exact: true }).click();
  const status = await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('get_desktop_status'));
  assert(status.tray_available && status.shortcut_registered, 'Native tray and global shortcut must be available');
  assert(status.preferences.check_updates === false, 'Automatic update checks must default off when loading old preferences');
  assert(await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('update_status')) === null, 'Startup must not implicitly fetch an update');
  assert(await page.evaluate(async () => {
    try { await window.__TAURI_INTERNALS__.invoke('install_desktop_update', { version: '99.0.0', token: '', confirm: false }); return false; }
    catch (error) { return String(error).includes('update_confirmation_required'); }
  }), 'Native installation must require explicit consent');
  step = 'native Passkey approval window';
  native('close'); await wait(() => !native('state').visible);
  await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('show_desktop_approval'));
  await wait(() => native('state').visible);
  step = 'close, hidden search and repeat launch';
  native('close'); await wait(() => !native('state').visible);
  assert(child.exitCode === null, 'Close-to-tray must keep the process alive');
  native('shortcut'); await dialog().waitFor(); assert(native('state').visible, 'Global shortcut must show the hidden window');
  await dialog().getByRole('button', { name: 'Close', exact: true }).click();
  native('close'); await wait(() => !native('state').visible);
  const second = spawn(executable, [], { cwd: root, env, windowsHide: true, stdio: 'ignore' });
  try { await wait(() => second.exitCode !== null); } finally { if (second.exitCode === null) second.kill(); }
  await wait(() => native('state').visible);
  step = 'native preferences and unsaved exit';
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByLabel('Global shortcut', { exact: true }).selectOption('');
  await wait(async () => !(await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('get_desktop_status'))).shortcut_registered);
  await page.getByLabel('Global shortcut', { exact: true }).selectOption('Control+Shift+Space');
  await wait(async () => (await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('get_desktop_status'))).shortcut_registered);
  const trayCheckbox = page.getByLabel('Keep running in the tray when the window closes', { exact: true });
  assert(await trayCheckbox.isChecked(), 'Close-to-tray starts enabled');
  // The controlled value is acknowledged asynchronously by the native command.
  await trayCheckbox.click();
  await wait(async () => !await trayCheckbox.isChecked());
  await wait(async () => !(await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('get_desktop_status'))).preferences.close_to_tray);
  await page.getByRole('button', { name: 'Passwords', exact: true }).click();
  await page.getByRole('button', { name: 'Add password', exact: true }).click();
  await page.getByLabel('Website or app name', { exact: true }).fill('Generated unsaved native draft');
  native('close'); await page.getByRole('button', { name: 'Keep editing', exact: true }).click();
  assert(await page.getByLabel('Website or app name', { exact: true }).inputValue() === 'Generated unsaved native draft', 'Cancelled native exit must retain draft');
  const apiAddress = await page.evaluate(async () => (await window.__TAURI_INTERNALS__.invoke('get_api_runtime_config')).base_url);
  native('close'); await page.getByRole('button', { name: 'Discard and close', exact: true }).click();
  await wait(() => child.exitCode !== null); browser = undefined;
  await wait(async () => { try { await fetch(`${apiAddress}/browser/discovery`); return false; } catch { return true; } });
  step = 'restart, locked shortcut and persisted settings';
  await start();
  assert(!(await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('windows_hello_status'))).ready, 'Hello requires master enrollment after restart');
  native('shortcut');
  assert(await dialog().count() === 0, 'Locked shortcut must not expose entries');
  await page.getByLabel('Master password', { exact: true }).fill(master);
  await page.getByRole('button', { name: 'Unlock', exact: true }).click();
  await dialog().getByRole('option').waitFor();
  assert(await dialog().getByRole('option').count() === 1, 'Unsaved draft must not have persisted');
  await dialog().getByRole('button', { name: 'Close', exact: true }).click();
  const restored = await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('get_desktop_status'));
  assert(!restored.preferences.close_to_tray, 'Preferences must survive restart');
  native('close'); await wait(() => child.exitCode !== null); browser = undefined;
  console.log(JSON.stringify({ nativeQuickSearch: true, globalShortcutFromAnotherWindow: true, closeToTray: true, singleInstance: true, dirtyExit: true, lockedRestart: true, preferencesPersisted: true, qrImageUnderNativeCsp: true, shortcutToggle: true, sidecarShutdown: true, nativeSessionNotifications: true, nativeSuspendNotifications: true, pendingDraftClearedOnSystemLock: true, resumeStayedLocked: true, passkeyApprovalWindow: true }));
} catch (error) {
  console.error(`Generated desktop lifecycle failed at ${step}: ${String(error.message).split(master).join('[generated]').split(password).join('[generated]')}`);
  process.exitCode = 1;
} finally {
  await browser?.close().catch(() => {});
  if (child && child.exitCode === null) { const exited = new Promise(accept => child.once('exit', accept)); child.kill(); await exited; }
  const target = resolve(isolated);
  if (dirname(target) !== resolve(tmpdir()) || !basename(target).startsWith('vault-desktop-generated-')) throw new Error('Invalid generated cleanup directory');
  await rm(target, { recursive: true, force: true, maxRetries: 10, retryDelay: 300 });
}
