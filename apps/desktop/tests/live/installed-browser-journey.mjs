import { chromium } from '../../node_modules/playwright/index.mjs';
import { spawn } from 'node:child_process';
import { createServer } from 'node:http';
import { randomBytes } from 'node:crypto';
import { join } from 'node:path';

const assert = (value, message) => { if (!value) throw new Error(message); };
export async function installedBrowsers({ root, data, desktop, api, runtime, master, extension, phase }) {
  const site = createServer((_req, res) => { res.setHeader('Content-Type', 'text/html'); res.end('<!doctype html><form onsubmit="event.preventDefault()"><input autocomplete="username"><input type="password" autocomplete="current-password"><input autocomplete="one-time-code"></form>'); });
  await new Promise(done => site.listen(0, '127.0.0.1', done));
  const siteUrl = `http://127.0.0.1:${site.address().port}`;
  try {
    for (const channel of ['chrome', 'msedge']) {
      let context, rp, step = 'launch';
      try {
        context = await chromium.launchPersistentContext(join(data, `browser-${channel}`), { channel, headless: true, ignoreDefaultArgs: ['--disable-extensions'], args: ['--enable-unsafe-extension-debugging'] });
        const cdp = await context.browser().newBrowserCDPSession();
        const version = await cdp.send('Browser.getVersion');
        const { id } = await cdp.send('Extensions.loadUnpacked', { path: extension });
        const website = await context.newPage(); await website.goto(siteUrl);
        const popup = await context.newPage(); popup.setDefaultTimeout(20000);
        await popup.goto(`chrome-extension://${id}/popup.html?lang=en`);
        const tabs = await popup.evaluate(() => chrome.tabs.query({}));
        const tabId = tabs.find(value => value.url?.startsWith(siteUrl)).id;
        await popup.goto(`chrome-extension://${id}/popup.html?tab=${tabId}&lang=en`);
        step = 'authorization';
        const identity = await popup.evaluate(() => vaultBrowserIdentity.read().then(value => value?.deviceId || null));
        if (phase === 'restart') assert(Boolean(identity), 'Browser authorization was lost after installed restart');
        if (!identity) {
          const pairing = await api('/browser/pairing-code');
          await popup.locator('#sidecar-url').fill(runtime.base_url.replace(/\/api$/, ''));
          await popup.locator('#pairing-code').fill(pairing.pairing_code);
          await popup.locator('#device-name').fill(`Generated installed ${channel}`);
          await popup.locator('#pair-form button[type=submit]').click();
        }
        await popup.locator('#accounts').waitFor();
        step = 'fill and verification code';
        const password = randomBytes(24).toString('hex');
        const title = `Generated installed ${channel} ${phase}`;
        const entry = await api('/entries', { title, username: 'generated-user', password, url: siteUrl, totp_secret: 'GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ' });
        await popup.reload(); await popup.locator('#accounts').waitFor();
        await popup.locator('button.match').filter({ hasText: title }).click();
        await website.waitForFunction(() => document.querySelector('[type=password]').value.length > 0);
        assert(await website.locator('[type=password]').inputValue() === password, 'Installed extension fill changed a password');
        const before = await api(`/entries/${entry.id}/totp`, null, 'GET');
        await popup.getByRole('button', { name: `Fill verification code ${title}`, exact: true }).click();
        await website.waitForFunction(() => /^\d{6}$/.test(document.querySelector('[autocomplete="one-time-code"]').value));
        const after = await api(`/entries/${entry.id}/totp`, null, 'GET');
        assert([before.code, after.code].includes(await website.locator('[autocomplete="one-time-code"]').inputValue()), 'Installed TOTP does not match');
        step = 'save and change password';
        await popup.locator('#add').click();
        await popup.locator('#save-title').fill(`Generated saved ${channel} ${phase}`);
        await popup.locator('#save-username').fill(`generated-${phase}`);
        await popup.locator('#generate').click();
        await popup.waitForFunction(() => document.querySelector('#save-password').value.length > 0);
        const generated = await popup.locator('#save-password').inputValue();
        await popup.getByRole('button', { name: 'Review saving', exact: true }).click();
        await popup.getByLabel("I've confirmed this password works on this website.").check();
        await popup.getByRole('button', { name: 'Confirm save', exact: true }).click();
        await popup.waitForFunction(() => document.querySelector('#status').dataset.key === 'saved');
        const stored = await api('/entries', null, 'GET');
        const saved = stored.find(value => value.title === `Generated saved ${channel} ${phase}`);
        assert(saved && (await api(`/entries/${saved.id}?reveal=true`, null, 'GET')).password === generated, 'Installed browser save failed');
        // Update through the same popup review path, retaining the previous secret.
        await popup.getByRole('button', { name: `Update ${saved.title} ${saved.username}`, exact: true }).click();
        const changed = randomBytes(24).toString('hex');
        await popup.locator('#save-password').fill(changed);
        await popup.getByRole('button', { name: 'Review saving', exact: true }).click();
        await popup.getByLabel("I've confirmed this password works on this website.").check();
        await popup.getByRole('button', { name: 'Confirm save', exact: true }).click();
        await popup.waitForFunction(() => document.querySelector('#status').dataset.key === 'saved');
        assert((await api(`/entries/${saved.id}?reveal=true`, null, 'GET')).password === changed, 'Installed browser change-password failed');

        if (phase === 'initial') {
          step = 'Passkey';
          rp = spawn(join(root, '.venv/Scripts/python.exe'), [join(root, 'tests/helpers/passkey_rp.py')], { cwd: data, windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'] });
          const port = await new Promise((done, reject) => {
            let output = ''; const timer = setTimeout(() => reject(new Error('Generated RP timeout')), 15000);
            rp.stdout.on('data', chunk => { output += chunk.toString(); if (output.includes('\n')) { clearTimeout(timer); done(JSON.parse(output.split('\n')[0]).port); } });
            rp.once('exit', () => { clearTimeout(timer); reject(new Error('Generated RP stopped')); });
          });
          const origin = `http://localhost:${port}`;
          await website.goto(origin);
          await popup.reload(); await popup.locator('#accounts').waitFor();
          await popup.locator('#inline-heading').click();
          await popup.locator('#inline-site').fill(origin);
          await popup.locator('#inline-enable-site').click();
          await popup.getByText('Suggestions are enabled for this website.', { exact: true }).waitFor();
          await popup.locator('#passkey-enabled').check();
          await website.reload(); await website.bringToFront();
          await website.locator('#create').click();
          const dialog = desktop.getByRole('dialog');
          await dialog.getByRole('heading', { name: 'Create a Passkey', exact: true }).waitFor();
          await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
          await website.waitForFunction(() => document.querySelector('#result').textContent === 'NotAllowedError');
          for (const operation of ['create', 'get']) {
            await website.locator(`#${operation}`).click();
            await dialog.getByLabel('Master password', { exact: true }).fill(master);
            await dialog.getByRole('button', { name: 'Confirm', exact: true }).click();
            await website.waitForFunction(text => document.querySelector('#result').textContent === text, operation === 'create' ? 'Registered' : 'Signed in');
          }
        } else {
          step = 'revocation';
          const deviceId = await popup.evaluate(() => vaultBrowserIdentity.read().then(value => value.deviceId));
          await api(`/browser/devices/${deviceId}`, {}, 'DELETE');
          await popup.evaluate(() => chrome.storage.session.clear()); await popup.reload();
          await popup.locator('#pair-form').waitFor();
          assert(await popup.locator('#accounts').isHidden(), 'Revoked installed browser retained access');
        }
        console.log(JSON.stringify({ browser: version.product, packagedExtension: true, phase, fill: true, totp: true, saveAndChange: true, passkey: phase === 'initial', revoked: phase === 'restart' }));
      } catch (error) { throw new Error(`Installed ${channel} failed at ${step}: ${error.name}: ${String(error.message).split('\n')[0]}`); }
      finally {
        await context?.close();
        if (rp && rp.exitCode === null && rp.signalCode === null) { const exited = new Promise(done => rp.once('exit', done)); rp.kill(); await exited; }
      }
    }
  } finally { await new Promise(done => site.close(done)); }
}
