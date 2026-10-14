import { spawn } from 'node:child_process';
import { join } from 'node:path';
import { createInterface } from 'node:readline';

export async function exerciseAutoType({ page, root, entryId, username, password, token, focusMain }) {
  const target = spawn('powershell.exe', ['-NoProfile', '-STA', '-ExecutionPolicy', 'Bypass', '-File', join(root, 'apps/desktop/tests/live/auto-type-target.ps1')], { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
  let pending, error = false;
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const lines = createInterface({ input: target.stdout });
  lines.on('line', line => { const waiter = pending; pending = undefined; if (waiter) { try { waiter.resolve(JSON.parse(line)); } catch { waiter.reject(new Error('Invalid generated target response')); } } });
  target.stderr.on('data', () => { error = true; });
  function response(command) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { pending = undefined; reject(new Error('Generated target timed out')); }, 10_000);
      pending = { resolve: value => { clearTimeout(timer); resolve(value); }, reject: reason => { clearTimeout(timer); reject(reason); } };
      if (command) target.stdin.write(command + '\n');
    });
  }
  async function capture(mode = 'focus') {
    const capturing = page.evaluate(() => window.__TAURI_INTERNALS__.invoke('capture_type_target'));
    // Keep only this generated window selected while the native picker counts
    // down. CI's runner shell may otherwise reclaim foreground during startup.
    let finished = false;
    const settled = capturing.finally(() => { finished = true; });
    while (!finished) {
      assert((await response(mode)).focused, 'Generated target did not acquire foreground focus');
      await Promise.race([settled, new Promise(resolve => setTimeout(resolve, 150))]);
    }
    const selected = await capturing;
    assert(selected.title === 'Vault generated auto-type target' && selected.application.toLowerCase() === 'powershell.exe', `Auto-type capture must bind only the isolated generated target (title=${selected.title === 'Vault generated auto-type target'}, application=${selected.application.toLowerCase() === 'powershell.exe'})`);
    return selected.id;
  }
  async function type(id, delayMs = 20) {
    await focusMain(); // The user confirms in the foreground vault window.
    return page.evaluate(async ({ id, entryId, delayMs, token }) => {
      try { await window.__TAURI_INTERNALS__.invoke('start_auto_type', { targetId: id, entryId, token, sequence: 'login', delayMs }); return 'typed'; }
      catch (reason) { return String(reason); }
    }, { id, entryId, delayMs, token });
  }
  try {
    await response();
    let id = await capture();
    const typed = await type(id);
    assert(typed === 'typed', `Native application typing failed (${typed})`);
    let state;
    for (let attempt = 0; attempt < 30; attempt++) {
      state = await response('read');
      if (state.username === username && state.password === password) break;
      await new Promise(resolve => setTimeout(resolve, 50));
    }
    assert(state.username === username && state.password === password && state.submissions === 0 && !state.other, `Native literal Unicode/Tab typing or no-submit contract failed (userLength=${state.username.length}/${username.length}, passLength=${state.password.length}/${password.length}, userPrefix=${username.startsWith(state.username)}, passPrefix=${password.startsWith(state.password)}, field=${state.field}, focused=${state.focused}, submitted=${state.submissions !== 0}, diverted=${Boolean(state.other)})`);
    assert(await type(id) === 'type_target', 'Target selection must be one-use');
    id = await capture('divert');
    assert(await type(id, 70) === 'type_focus', 'Focus change must stop native typing');
    state = await response('read');
    assert(state.password.length >= 3 && state.password.length < password.length && !state.other && state.submissions === 0, 'Remaining credentials must not enter the distraction window');
    id = await capture();
    const typing = type(id, 70);
    for (let attempt = 0; attempt < 20; attempt++) {
      state = await response('read');
      if (state.username.length > 2) break;
      await new Promise(resolve => setTimeout(resolve, 30));
    }
    assert(state.username.length > 2, 'Generated typing did not start before cancellation');
    await page.evaluate(() => window.__TAURI_INTERNALS__.invoke('cancel_auto_type'));
    assert(await typing === 'type_cancelled', 'Explicit cancel must stop an active native operation');
    state = await response('read');
    assert(!state.password && !state.other && state.submissions === 0, 'Cancelled operation must not proceed to the password');
    id = await capture();
    await response('rename');
    assert(await type(id) === 'type_target', 'Changed window identity must be refused');
    state = await response('read');
    assert(!state.username && !state.password && !state.other && !state.submissions, 'Invalid target must receive no input');
    assert(!error, 'Generated target emitted an error');
  } finally {
    target.stdin.write('exit\n');
    await new Promise(resolve => { if (target.exitCode !== null) return resolve(); target.once('exit', resolve); setTimeout(() => { target.kill(); resolve(); }, 2000).unref(); });
    lines.close();
  }
}
