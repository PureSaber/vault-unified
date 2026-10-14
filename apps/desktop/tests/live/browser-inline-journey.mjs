import { createServer } from 'node:http';

export async function inlineJourney({ browser, context, api, password, assert }) {
  const { website, popup, siteUrl } = browser;
  let embedded, step = 'enable website';
  const cdp = await context.newCDPSession(website);
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  async function accessibleButton(name, frameId) {
    for (let i = 0; i < 100; i++) {
      const tree = await cdp.send('Accessibility.getFullAXTree', frameId ? { frameId } : {});
      const node = tree.nodes.find(node => node.role?.value === 'button' && (typeof name === 'string' ? node.name?.value === name : name.test(node.name?.value || '')));
      if (node?.backendDOMNodeId) return node;
      await pause(100);
    }
    throw new Error(`Inline button missing: ${String(name)}`);
  }
  async function clickButton(name, frameId) {
    const node = await accessibleButton(name, frameId);
    const { model } = await cdp.send('DOM.getBoxModel', { backendNodeId: node.backendDOMNodeId });
    const bounds = model.content;
    await website.mouse.click((bounds[0] + bounds[4]) / 2, (bounds[1] + bounds[5]) / 2);
  }
  async function selectAccount(input, name = /Generated restart account/, frameId) {
    await input.click();
    await clickButton('Choose account from Vault Unified', frameId);
    await clickButton(name, frameId);
  }
  async function enable(origin) {
    await popup.bringToFront();
    const controls = popup.locator('#inline-controls');
    if (!await controls.evaluate(element => element.open)) await controls.locator('summary').click();
    await popup.locator('#inline-site').fill(origin);
    await popup.locator('#inline-enable-site').click();
    await popup.getByText('Suggestions are enabled for this website.', { exact: true }).waitFor();
  }
  try {
    await enable(siteUrl);
    step = 'username step';
    await website.bringToFront();
    await website.goto(`${siteUrl}/step-one`);
    await selectAccount(website.locator('[autocomplete=username]'));
    await website.waitForFunction(() => document.querySelector('[autocomplete=username]').value === 'generated-user');
    assert(await website.evaluate(() => document.querySelector('form').dataset.submitted !== 'yes'), 'Username step submitted automatically');
    step = 'password step';
    await website.goto(`${siteUrl}/step-two`);
    await selectAccount(website.locator('[type=password]'));
    await website.waitForFunction(() => document.querySelector('[type=password]').value.length > 0);
    assert(await website.locator('[type=password]').inputValue() === password, 'Password step did not fill');
    step = 'complex form';
    await website.goto(`${siteUrl}/complex`);
    await selectAccount(website.locator('#second-password'));
    await website.waitForFunction(() => document.querySelector('#second-password').value.length > 0);
    assert(await website.locator('#first-password').inputValue() === '', 'Inline fill changed a different form');
    assert(await website.locator('#second-user').inputValue() === 'generated-user', 'Inline fill did not use the selected form');
    assert(await website.locator('#second-password').inputValue() === password, 'Selected password field did not fill');
    step = 'synthetic click and replaced target';
    await website.goto(`${siteUrl}/step-two`);
    await website.locator('[type=password]').click();
    await clickButton('Choose account from Vault Unified');
    const row = await accessibleButton(/Generated restart account/);
    const { object } = await cdp.send('DOM.resolveNode', { backendNodeId: row.backendDOMNodeId });
    await cdp.send('Runtime.callFunctionOn', { objectId: object.objectId, functionDeclaration: 'function(){ this.click(); }' });
    await pause(200);
    assert(await website.locator('[type=password]').inputValue() === '', 'A synthetic page click filled a password');
    await website.evaluate(() => document.querySelector('[type=password]').replaceWith(document.createElement('input')));
    await clickButton(/Generated restart account/);
    assert(await website.locator('input').inputValue() === '', 'A replaced field received credentials');

    embedded = createServer((_request, response) => { response.setHeader('Content-Type', 'text/html'); response.end('<!doctype html><form><input autocomplete="username"><input type="password" autocomplete="current-password"></form>'); });
    await new Promise(resolve => embedded.listen(0, '127.0.0.1', resolve));
    step = 'cross-origin consent';
    const embeddedOrigin = `http://127.0.0.1:${embedded.address().port}`;
    await api('/entries', { title: 'Generated embedded account', username: 'generated-frame-user', password, url: embeddedOrigin });
    await website.goto(`${siteUrl}/embedded?origin=${encodeURIComponent(embeddedOrigin)}`);
    const frame = website.frameLocator('iframe');
    step = 'unapproved frame';
    await frame.locator('[type=password]').click();
    await pause(200);
    assert(await frame.locator('[type=password]').inputValue() === '', 'Unapproved frame was filled');
    await enable(embeddedOrigin);
    step = 'open frame chooser';
    await website.bringToFront();
    const frameTree = await cdp.send('Page.getFrameTree');
    const frameId = frameTree.frameTree.childFrames.find(value => value.frame.url.startsWith(embeddedOrigin)).frame.id;
    await selectAccount(frame.locator('[type=password]'), /Generated embedded account/, frameId);
    let confirmation;
    for (let i = 0; i < 100 && !confirmation; i++) { confirmation = context.pages().find(page => page.url().includes('/frame-confirm.html?')); if (!confirmation) await pause(100); }
    assert(Boolean(confirmation), 'Cross-origin confirmation did not open');
    step = 'cancel frame confirmation';
    await confirmation.getByText(embeddedOrigin, { exact: true }).waitFor();
    assert(await frame.locator('[type=password]').inputValue() === '', 'Frame filled before confirmation');
    await confirmation.getByRole('button', { name: 'Cancel', exact: true }).click();
    assert(await frame.locator('[type=password]').inputValue() === '', 'Cancelled frame consent filled credentials');
    await website.bringToFront();
    step = 'reopen frame chooser';
    await selectAccount(frame.locator('[type=password]'), /Generated embedded account/, frameId);
    for (let i = 0; i < 100; i++) { confirmation = context.pages().find(page => page.url().includes('/frame-confirm.html?')); if (confirmation) break; await pause(100); }
    step = 'approve frame confirmation';
    await confirmation.getByRole('button', { name: 'Confirm fill into this website', exact: true }).click();
    await frame.locator('[type=password]').evaluate(input => new Promise((resolve, reject) => {
      let remaining = 50; const interval = setInterval(() => { if (input.value) { clearInterval(interval); resolve(true); } else if (!--remaining) { clearInterval(interval); reject(new Error('Frame fill timed out')); } }, 100);
    }));
    assert(await frame.locator('[type=password]').inputValue() === password, 'Confirmed frame did not receive the selected password');
    await popup.bringToFront();
    await popup.locator('#inline-disable-all').click();
    await popup.getByText('Suggestions are off for this website.', { exact: true }).waitFor();
    await website.goto(siteUrl);
    const scripts = await popup.evaluate(() => chrome.scripting.getRegisteredContentScripts());
    assert(!scripts.some(script => script.id === 'vault-unified-inline'), 'Disabled suggestions stayed registered');
  } catch (error) { throw new Error(`Inline ${step}: ${error.message}`); }
  finally {
    await cdp.detach();
    if (embedded) { embedded.closeAllConnections(); await new Promise(resolve => embedded.close(resolve)); }
  }
}
