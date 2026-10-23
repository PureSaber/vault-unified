importScripts("identity.js", "connection.js", "connect.js", "passkey-worker.js");

const inlineKey = "vaultUnifiedInlinePreferences";
const scriptId = "vault-unified-inline";
const pendingFrames = new Map();
const selections = new Map();
let scriptUpdates = Promise.resolve();
let settingsUpdates = Promise.resolve();
const fail = key => { throw Object.assign(new Error(), { key }); };
function originOf(value) {
  const url = new URL(value);
  if (!["https:", "http:"].includes(url.protocol) || url.username || url.password || url.origin === "null") fail("pageChanged");
  return url.origin;
}
function permissionPattern(origin) { const url = new URL(origin); return `${url.protocol}//${url.hostname}/*`; }
async function preferences() {
  const stored = (await chrome.storage.local.get(inlineKey))[inlineKey] || {};
  const origins = values => Array.isArray(values) ? [...new Set(values.slice(0, 1000).flatMap(value => {
    try { return typeof value === "string" ? [originOf(value)] : []; } catch { return []; }
  }))] : [];
  return { all: stored.all === true, passkeys: stored.passkeys === true, sites: origins(stored.sites), excluded: origins(stored.excluded), language: stored.language === "zh" ? "zh" : "en" };
}
async function allowed(origin) {
  const settings = await preferences();
  return !settings.excluded.includes(origin) && (settings.all || settings.sites.includes(origin))
    && await chrome.permissions.contains({ origins: [permissionPattern(origin)] });
}
function extensionPage(sender, filename) {
  try { const url = new URL(sender.url); return sender.id === chrome.runtime.id && url.protocol === "chrome-extension:" && url.hostname === chrome.runtime.id && url.pathname === `/${filename}`; }
  catch { return false; }
}
async function frameContext(sender) {
  if (sender.id !== chrome.runtime.id || !Number.isInteger(sender.tab?.id) || !Number.isInteger(sender.frameId)
      || typeof sender.documentId !== "string" || sender.documentLifecycle !== "active") fail("pageChanged");
  const origin = originOf(sender.url);
  if (sender.origin && sender.origin !== origin) fail("pageChanged");
  if (!await allowed(origin)) fail("siteDisabled");
  const tab = await chrome.tabs.get(sender.tab.id);
  const topOrigin = originOf(tab.url);
  return { tabId: tab.id, documentId: sender.documentId, frameId: sender.frameId, origin, topOrigin };
}
async function stillCurrent(context) {
  const tab = await chrome.tabs.get(context.tabId);
  if (!tab.active || originOf(tab.url) !== context.topOrigin || !await allowed(context.origin)) fail("pageChanged");
  const result = await chrome.scripting.executeScript({ target: { tabId: context.tabId, documentIds: [context.documentId] }, func: () => location.origin });
  if (result.length !== 1 || result[0].result !== context.origin) fail("pageChanged");
}
async function fill(context, message) {
  await stillCurrent(context);
  const started = Date.now();
  const value = message.mode === "otp"
    ? await vaultBrowserConnection.connectedRequest("/totp", { entry_id: message.entryId, url: context.origin })
    : await vaultBrowserConnection.connectedRequest("/fill", { entry_id: message.entryId, url: context.origin, field: message.mode });
  await stillCurrent(context);
  const values = message.mode === "otp" ? { otp: value.code, expiresAt: started + value.remaining_seconds * 1000 } : value;
  try {
    const outcome = await chrome.tabs.sendMessage(context.tabId, { type: "vault-inline-deliver", nonce: message.nonce, origin: context.origin, values }, { documentId: context.documentId });
    if (!outcome?.filled) fail("targetChanged");
    selections.set(context.tabId, { entryId: message.entryId, origin: context.origin, expires: Date.now() + 300_000 });
    return { filled: true };
  } finally { if (values.password) values.password = ""; if (values.otp) values.otp = ""; }
}
function synchronizeScripts() { scriptUpdates = scriptUpdates.catch(() => {}).then(updateScripts); return scriptUpdates; }
async function cancelFrame(id) {
  const pending = pendingFrames.get(id);
  pendingFrames.delete(id);
  if (pending) await chrome.tabs.sendMessage(pending.context.tabId, { type: "vault-inline-cancel", nonce: pending.message.nonce }, { documentId: pending.context.documentId }).catch(() => {});
}
async function updateScripts() {
  const settings = await preferences();
  const grants = (await chrome.permissions.getAll()).origins || [];
  const desired = settings.all ? ["http://*/*", "https://*/*"] : [...new Set(settings.sites.map(permissionPattern))];
  const matches = [];
  for (const pattern of desired) if (grants.includes(pattern) || await chrome.permissions.contains({ origins: [pattern] })) matches.push(pattern);
  const existing = await chrome.scripting.getRegisteredContentScripts({ ids: [scriptId, "vault-passkey-bridge", "vault-passkey-main"] });
  const desiredScripts = matches.length ? [{ id: scriptId, matches, js: ["inline.js"], allFrames: true, runAt: "document_idle", persistAcrossSessions: true, world: "ISOLATED" }] : [];
  if (matches.length && settings.passkeys) {
    desiredScripts.push({ id: "vault-passkey-bridge", matches, js: ["passkey-bridge.js"], allFrames: true, runAt: "document_start", persistAcrossSessions: true, world: "ISOLATED" });
    desiredScripts.push({ id: "vault-passkey-main", matches, js: ["passkey-main.js"], allFrames: true, runAt: "document_start", persistAcrossSessions: true, world: "MAIN" });
  }
  const removed = existing.filter(value => !desiredScripts.some(script => script.id === value.id)).map(value => value.id);
  if (removed.length) await chrome.scripting.unregisterContentScripts({ ids: removed });
  for (const script of desiredScripts) {
    if (existing.some(value => value.id === script.id)) await chrome.scripting.updateContentScripts([script]);
    else await chrome.scripting.registerContentScripts([script]);
  }
}
async function changeSettings(message) {
  const settings = await preferences();
  const origin = originOf(message.origin);
  if (message.action === "passkeys-on" || message.action === "passkeys-off") {
    settings.passkeys = message.action === "passkeys-on";
  } else if (message.action === "enable-all") {
    if (!await chrome.permissions.contains({ origins: ["http://*/*", "https://*/*"] })) fail("siteDisabled");
    settings.all = true; settings.excluded = [];
  } else if (message.action === "disable-all") {
    settings.all = false; settings.sites = []; settings.excluded = [];
  } else if (message.action === "enable-site") {
    if (!await chrome.permissions.contains({ origins: [permissionPattern(origin)] })) fail("siteDisabled");
    if (!settings.sites.includes(origin)) settings.sites.push(origin);
    settings.excluded = settings.excluded.filter(value => value !== origin);
  } else if (message.action === "disable-site") {
    settings.sites = settings.sites.filter(value => value !== origin);
    if (!settings.excluded.includes(origin)) settings.excluded.push(origin);
  } else fail("requestError");
  if (settings.sites.length > 1000 || settings.excluded.length > 1000) fail("requestError");
  settings.language = message.language === "zh" ? "zh" : "en";
  await chrome.storage.local.set({ [inlineKey]: settings });
  if (message.action.startsWith("disable")) {
    selections.clear();
    for (const [id, value] of pendingFrames) if (message.action === "disable-all" || value.context.origin === origin) await cancelFrame(id);
  }
  if (message.action === "disable-all") {
    const origins = ((await chrome.permissions.getAll()).origins || []).filter(value => !["http://127.0.0.1/*", "http://localhost/*"].includes(value));
    if (origins.length) await chrome.permissions.remove({ origins });
  }
  await synchronizeScripts();
  for (const tab of await chrome.tabs.query({})) {
    if (!/^https?:/.test(tab.url || "")) continue;
    await chrome.tabs.sendMessage(tab.id, { type: "vault-inline-reset" }).catch(() => {});
    if ((message.action.startsWith("enable") || message.action === "passkeys-on") && tab.id === message.tabId) {
      await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ["inline.js"] }).catch(() => {});
      if (settings.passkeys && await allowed(originOf(tab.url))) {
        await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ["passkey-bridge.js"] }).catch(() => {});
        await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, world: "MAIN", files: ["passkey-main.js"] }).catch(() => {});
      }
    }
  }
  return { enabled: await allowed(origin), all: settings.all };
}
async function handle(message, sender) {
  if (["vault-passkey-begin", "vault-passkey-cancel"].includes(message.type)) return handlePasskey(message, sender);
  if (extensionPage(sender, "popup.html")) {
    if (message.type === "vault-inline-settings") {
      settingsUpdates = settingsUpdates.catch(() => {}).then(() => changeSettings(message));
      return settingsUpdates;
    }
    if (message.type === "vault-inline-status") { const settings = await preferences(); return { enabled: await allowed(originOf(message.origin)), all: settings.all, passkeys: settings.passkeys }; }
    // Only the extension's own popup can start or watch a connection request.
    if (message.type === "vault-connect-start") return vaultBrowserConnect.start();
    if (message.type === "vault-connect-state") return vaultBrowserConnect.poll();
    if (message.type === "vault-connect-cancel") return vaultBrowserConnect.cancel();
    if (message.type === "vault-connect-ack") return vaultBrowserConnect.acknowledge();
  }
  if (extensionPage(sender, "frame-confirm.html")) {
    const pending = pendingFrames.get(message.id);
    if (!pending || pending.expires <= Date.now()) fail("expired");
    if (message.type === "vault-frame-info") return { origin: pending.context.origin, topOrigin: pending.context.topOrigin, title: pending.title, username: pending.username, language: pending.language, expires: pending.expires };
    if (message.type === "vault-frame-cancel") { await cancelFrame(message.id); return { cancelled: true }; }
    if (message.type === "vault-frame-approve") {
      pendingFrames.delete(message.id);
      return fill(pending.context, pending.message);
    }
  }
  if (!["vault-inline-matches", "vault-inline-select", "vault-inline-check"].includes(message.type)) fail("requestError");
  const context = await frameContext(sender);
  const settings = await preferences();
  if (message.type === "vault-inline-check") return { enabled: true, language: settings.language };
  if (message.type === "vault-inline-matches") {
    const result = await vaultBrowserConnection.connectedRequest(`/matches?url=${encodeURIComponent(context.origin)}`);
    await stillCurrent(context);
    const selection = selections.get(context.tabId);
    const preferred = selection?.origin === context.origin && selection.expires > Date.now() ? selection.entryId : null;
    return { matches: result.matches, origin: context.origin, preferred, language: settings.language };
  }
  if (typeof message.entryId !== "string" || !message.entryId.length || message.entryId.length > 128 || !/^[a-f0-9-]{36}$/.test(message.nonce || "")
      || !["login", "username", "password", "otp"].includes(message.mode)) fail("requestError");
  if (context.origin === context.topOrigin) return fill(context, message);
  const result = await vaultBrowserConnection.connectedRequest(`/matches?url=${encodeURIComponent(context.origin)}`);
  const entry = result.matches.find(value => value.id === message.entryId);
  if (!entry) fail("pageChanged");
  for (const [id, pending] of pendingFrames) if (pending.expires <= Date.now()) pendingFrames.delete(id);
  if (pendingFrames.size >= 4) fail("requestError");
  const id = crypto.randomUUID();
  pendingFrames.set(id, { context, message, title: entry.title, username: entry.username, language: settings.language, expires: Date.now() + 60_000 });
  try { await chrome.windows.create({ url: chrome.runtime.getURL(`frame-confirm.html?id=${id}`), type: "popup", width: 500, height: 460 }); }
  catch (error) { pendingFrames.delete(id); throw error; }
  return { confirmation: true };
}
chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (!message?.type?.startsWith("vault-")) return false;
  handle(message, sender).then(respond).catch(error => respond({ error: error.key || "requestError" }));
  return true;
});
chrome.commands.onCommand.addListener(async command => {
  if (command !== "choose-account") return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) return;
  await chrome.tabs.sendMessage(tab.id, { type: "vault-inline-open" }).catch(async () => {
    await chrome.windows.create({ url: chrome.runtime.getURL(`popup.html?tab=${tab.id}`), type: "popup", width: 420, height: 640 });
  });
});
chrome.tabs.onRemoved.addListener(tabId => { selections.delete(tabId); for (const [id, value] of pendingFrames) if (value.context.tabId === tabId) pendingFrames.delete(id); });
chrome.permissions.onRemoved.addListener(() => {
  selections.clear();
  for (const id of pendingFrames.keys()) void cancelFrame(id);
  void synchronizeScripts().catch(() => {});
  void chrome.tabs.query({}).then(tabs => Promise.all(tabs.map(tab => chrome.tabs.sendMessage(tab.id, { type: "vault-inline-reset" }).catch(() => {})))).catch(() => {});
});
chrome.runtime.onInstalled.addListener(() => { void synchronizeScripts().catch(() => {}); });
chrome.alarms.onAlarm.addListener(value => { if (value.name === vaultBrowserConnect.alarm) void vaultBrowserConnect.poll().catch(() => {}); });
// A restarted worker continues a request that is still waiting for approval.
void vaultBrowserConnect.poll().catch(() => {});
chrome.runtime.onStartup.addListener(() => { void synchronizeScripts().catch(() => {}); });
