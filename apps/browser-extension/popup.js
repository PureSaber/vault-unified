const stateKey = "vaultUnifiedBrowserPairing";
const el = (id) => document.getElementById(id);
const windowOptions = new URL(location.href).searchParams;
const targetTabId = /^\d+$/.test(windowOptions.get("tab") || "") ? Number(windowOptions.get("tab")) : null;
let language = windowOptions.get("lang") || (navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en");
if (!["zh", "en"].includes(language)) language = "en";
if (targetTabId !== null) { document.body.classList.add("standalone"); el("keep-open").hidden = true; }
let currentState = null;
let currentTab = null;
let matches = [];
let preview = null;
let reviewedDraft = null;
let epoch = 0;
let busy = false;
let checking = false;

const messages = {
  language: ["语言", "Language"], address: ["本机地址", "Local address"],
  code: ["一次性配对码", "One-time pairing code"], pair: ["配对此浏览器", "Pair this browser"],
  remember: ["两端保持运行时，解锁后可恢复连接（最长 12 小时）。", "Reconnect after unlocking while both apps stay open (up to 12 hours)."],
  retry: ["已解锁，重新连接", "I've unlocked — reconnect"],
  keepOpen: ["用独立窗口完成注册／改密", "Open a window for registration / password changes"],
  capture: ["读取当前页面的账号", "Read login from this page"], add: ["手动添加", "Add manually"],
  saveHeading: ["保存账号", "Save an account"], details: ["账号信息", "Account details"],
  target: ["保存到", "Save to"], title: ["名称", "Name"], username: ["用户名或邮箱", "Username or email"],
  password: ["密码", "Password"], generate: ["生成密码", "Generate password"],
  show: ["显示密码", "Show password"], hide: ["隐藏密码", "Hide password"],
  fillNew: ["填入注册／新密码字段", "Fill registration / new-password fields"],
  draftHint: ["关闭此窗口或锁定会清除草稿。网站接受新密码后，再确认更新。", "Closing this window or locking clears the draft. Only confirm an update after the website accepts the password."],
  review: ["查看保存预览", "Review saving"], reviewHeading: ["保存前核对", "Check before saving"],
  confirmWorks: ["我已确认此密码可以在该网站使用。", "I've confirmed this password works on this website."],
  confirmSave: ["确认保存", "Confirm save"], edit: ["返回编辑", "Back to editing"],
  cancel: ["取消", "Cancel"], forget: ["解除配对", "Forget pairing"], update: ["更新", "Update"],
  newAccount: ["新增账号", "New account"], noUser: ["无用户名", "No username"],
  noMatches: ["此网站还没有保存的账号，可以读取页面或手动添加。", "No saved login URL matches this page."],
  choose: ["选择账号填充，或更新已修改的密码。", "Choose an entry to fill."],
  pairHint: ["在桌面端「连接」中生成一次性配对码。", "Create a one-time pairing code in Vault Unified Connections."],
  pairing: ["正在配对…", "Pairing…"], loading: ["正在连接…", "Connecting…"],
  locked: ["保险库已锁定，草稿已清除。请在桌面端解锁后重新连接。", "Vault locked; draft cleared. Unlock the desktop app, then reconnect."],
  unpaired: ["配对已失效，请在桌面端重新配对。", "Pairing expired. Create a new pairing code in the desktop app."],
  unavailable: ["无法连接桌面端，草稿已清除。请确认应用正在运行。", "Cannot connect to the desktop app; draft cleared. Check that it is running."],
  validPage: ["请先打开一个 http 或 https 网页。", "Open an http or https login page first."],
  addressError: ["请使用桌面端显示的本机 http://127.0.0.1 地址。", "Use the local http://127.0.0.1 address shown by Vault Unified"],
  pageChanged: ["页面已改变，请重新打开扩展后操作。", "The page changed. Reopen the extension before continuing."],
  filled: ["已填入登录表单。", "Filled the visible login form."],
  newFilled: ["已填入新密码字段。请完成网站操作后确认保存。", "Filled new-password fields. Complete the website action before confirming a save."],
  ambiguous: ["存在多个密码字段或登录表单，请手动填写账号信息。", "Multiple password fields or login forms were found. Nothing was filled."],
  newFlow: ["这是注册或改密页面。请在保存账号中填写新密码。", "This looks like a password creation or change form. Nothing was filled."],
  iframe: ["暂不支持内嵌框架中的表单，可手动添加账号。", "The login form may be inside an iframe, which this version does not fill."],
  shadow: ["暂不支持此页面的嵌套表单，可手动添加账号。", "The login form may use Shadow DOM, which this version does not fill."],
  empty: ["没有可用的密码，请先填写。", "The selected entry has no password to fill."],
  noField: ["未找到可用的密码字段，可手动添加账号。", "No supported visible password field was found. Nothing was filled."],
  captured: ["已读取页面内容，请核对账号并确认密码可用。", "Read the page. Check the account and confirm the password works."],
  generated: ["新密码已生成，尚未保存。", "Password generated; not saved yet."],
  saved: ["账号已保存到本地保险库。", "Account saved to the local vault."],
  saveUnknown: ["连接中断，保存结果待确认。请重新连接后检查账号。", "Connection interrupted; save result is unknown. Reconnect and check the account."],
  cancelled: ["已取消，保险库未改动。", "Cancelled. The vault was not changed."],
  forgotten: ["已解除此浏览器的配对。", "Pairing removed from this browser."],
  forgetFailed: ["无法在桌面端撤销连接，请保持锁定并在「连接」中取消配对后重试。", "Could not revoke the connection. Keep the vault locked and cancel pairing in desktop Connections before retrying."],
  confirmRequired: ["请先确认网站已接受此密码，再保存。", "Confirm that the website accepts this password before saving."],
  retained: ["原密码会保留在历史记录中，其他账号字段保持不变。", "The previous password stays in history. Other account fields are preserved."],
  created: ["将新增一个本地账号，不会自动写入外部服务。", "Creates a local account without writing to an external service."],
  changed: ["账号或保险库已改变，请重新查看保存预览。", "The account or vault changed. Review saving again."],
  duplicate: ["同名用户名已存在，请在「保存到」中选择已有账号进行更新。", "This username already exists. Select the existing account to update."],
  unchanged: ["此账号已保存相同信息，无需再次更新。", "This account already has these details."],
  requestError: ["操作未完成，请重试。", "The request could not be completed. Try again."],
};
const t = (key) => messages[key][language === "zh" ? 0 : 1];

function setStatus(key, error = false) {
  el("status").textContent = t(key);
  el("status").dataset.key = key;
  el("status").className = error ? "error" : "";
}
function localize() {
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  el("language").value = language;
  document.querySelectorAll("[data-i18n]").forEach((node) => { node.textContent = t(node.dataset.i18n); });
  if (el("status").dataset.key) el("status").textContent = t(el("status").dataset.key);
  el("reveal").textContent = t(el("save-password").type === "password" ? "show" : "hide");
  renderMatches();
  if (preview) renderPreview();
}
function normalizeAddress(value) {
  const url = new URL(value.trim());
  const path = url.pathname.replace(/\/+$/, "");
  if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname)
      || url.username || url.password || url.search || url.hash || (path && path !== "/api")) {
    throw Object.assign(new Error(), { key: "addressError" });
  }
  return url.origin;
}
async function request(path, options = {}, connection = false) {
  const state = currentState;
  const stamp = epoch;
  let response;
  try {
    response = await fetch(`${state.sidecarUrl}/api/browser${path}`, {
      method: "POST", ...options, signal: AbortSignal.timeout(8000),
      headers: { "Content-Type": "application/json",
        ...(connection ? { "X-Vault-Browser-Connection": state.connectionKey }
          : state.browserToken ? { "X-Vault-Browser-Token": state.browserToken } : {}), ...options.headers },
    });
  } catch {
    throw Object.assign(new Error(), { key: "unavailable", code: 0 });
  }
  const body = await response.json().catch(() => ({}));
  if (stamp !== epoch) throw Object.assign(new Error(), { key: "locked", code: 423 });
  if (!response.ok) {
    let key = response.status === 423 ? "locked" : "requestError";
    if (response.status === 401) key = "unpaired";
    if (response.status === 409) key = "changed";
    if (typeof body.detail === "string" && body.detail.includes("username already exists")) key = "duplicate";
    if (typeof body.detail === "string" && body.detail.includes("already has these details")) key = "unchanged";
    throw Object.assign(new Error(), { key, code: response.status });
  }
  return body;
}
function clearDraft() {
  preview = null;
  reviewedDraft = null;
  el("save-form").reset();
  el("save-password").value = "";
  el("save-password").type = "password";
  el("reveal").textContent = t("show");
  el("reveal").setAttribute("aria-pressed", "false");
  el("save-form").hidden = true;
  el("save-preview").hidden = true;
  el("draft-fields").hidden = false;
  el("preview-summary").textContent = "";
  el("preview-changes").textContent = "";
}
async function authFailure(error) {
  epoch += 1;
  clearDraft();
  matches = [];
  renderMatches();
  el("accounts").hidden = true;
  const remembered = Boolean(currentState?.connectionKey);
  if (!currentState?.browserToken) currentState = null;
  if (error.code === 401 && !remembered) {
    await chrome.storage.session.remove(stateKey);
    currentState = null;
  }
  el("pair-form").hidden = Boolean(currentState);
  el("retry").hidden = !currentState;
  el("forget").hidden = !currentState;
  setStatus(remembered && error.code === 401 ? "locked" : error.key || "requestError", true);
}
async function action(work) {
  if (busy) return;
  busy = true;
  document.querySelectorAll("button,input,select").forEach((node) => { node.disabled = true; });
  try { await work(); }
  catch (error) {
    if ([0, 401, 423].includes(error.code)) await authFailure(error);
    else setStatus(error.key || "requestError", true);
  } finally {
    busy = false;
    document.querySelectorAll("button,input,select").forEach((node) => { node.disabled = false; });
  }
}
async function selectedTab() {
  try {
    if (targetTabId !== null) return await chrome.tabs.get(targetTabId);
    return (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
  } catch { return null; }
}
async function samePage() {
  const tab = await selectedTab();
  if (!tab || tab.id !== currentTab?.id || new URL(tab.url).origin !== new URL(currentTab.url).origin) {
    epoch += 1;
    clearDraft();
    el("accounts").hidden = true;
    throw Object.assign(new Error(), { key: "pageChanged" });
  }
  return tab;
}
async function inject(func, values) {
  const tab = await samePage();
  const result = await chrome.scripting.executeScript({
    target: { tabId: tab.id }, func,
    args: [{ ...values, pageOrigin: new URL(tab.url).origin }],
  });
  return result[0]?.result || { reason: "no-password-field" };
}
function outcome(result) {
  const keys = { filled: "filled", "new-filled": "newFilled", "page-changed": "pageChanged",
    "ambiguous-password-fields": "ambiguous", "new-password-flow": "newFlow",
    iframe: "iframe", "shadow-dom": "shadow", "empty-password": "empty" };
  setStatus(keys[result.reason] || "noField", !["filled", "new-filled"].includes(result.reason));
}
async function fillMatch(entry) {
  const stamp = epoch;
  await samePage();
  const values = await request("/fill", { body: JSON.stringify({ entry_id: entry.id, url: new URL(currentTab.url).origin }) });
  if (stamp !== epoch) return;
  outcome(await inject(vaultUnifiedFillInputs, values));
}
function renderMatches() {
  el("matches").replaceChildren();
  const selected = el("save-target").value;
  el("save-target").replaceChildren(new Option(t("newAccount"), ""));
  for (const entry of matches) {
    const row = document.createElement("div");
    row.className = "match-row";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "match";
    button.textContent = entry.title;
    const username = document.createElement("small");
    username.textContent = entry.username || t("noUser");
    button.append(username);
    button.addEventListener("click", () => void action(() => fillMatch(entry)));
    const update = document.createElement("button");
    update.type = "button";
    update.className = "secondary update";
    update.textContent = t("update");
    update.setAttribute("aria-label", `${t("update")} ${entry.title} ${entry.username}`);
    update.addEventListener("click", () => openDraft(entry));
    row.append(button, update);
    el("matches").append(row);
    el("save-target").append(new Option(`${entry.title} · ${entry.username || t("noUser")}`, entry.id));
  }
  el("save-target").value = selected;
}
async function showMatches(successKey) {
  const stamp = epoch;
  setStatus("loading");
  const tab = await selectedTab();
  if (!tab?.id || !/^https?:\/\//.test(tab.url || "")) { setStatus("validPage", true); return; }
  currentTab = tab;
  const path = `/matches?url=${encodeURIComponent(new URL(tab.url).origin)}`;
  let result;
  try { result = await request(path, { body: "{}" }); }
  catch (error) {
    if (error.code !== 401 || !currentState?.connectionKey) throw error;
    try {
      const resumed = await request("/resume", { body: "{}" }, true);
      if (stamp !== epoch) return;
      currentState.browserToken = resumed.browser_token;
      await chrome.storage.session.set({ [stateKey]: currentState });
      result = await request(path, { body: "{}" });
    } catch (resumeError) {
      if (resumeError.code === 401) {
        await chrome.storage.session.remove(stateKey);
        currentState = null;
      }
      throw resumeError;
    }
  }
  if (stamp !== epoch) return;
  matches = result.matches;
  renderMatches();
  el("site").textContent = new URL(tab.url).origin;
  el("accounts").hidden = false;
  el("pair-form").hidden = true;
  el("retry").hidden = true;
  el("forget").hidden = false;
  setStatus(successKey || (matches.length ? "choose" : "noMatches"));
}
function openDraft(entry) {
  clearDraft();
  el("save-target").value = entry?.id || "";
  el("save-title").value = entry?.title || new URL(currentTab.url).hostname;
  el("save-username").value = entry?.username || "";
  el("accounts").hidden = true;
  el("save-form").hidden = false;
  requestAnimationFrame(() => { if (!el("save-form").hidden) el("save-password").focus(); });
}
function draft() {
  return { url: new URL(currentTab.url).origin, entry_id: el("save-target").value || null,
    title: el("save-title").value.trim(), username: el("save-username").value,
    password: el("save-password").value };
}
function renderPreview() {
  el("preview-summary").textContent = `${t(preview.action === "update" ? "update" : "newAccount")} · ${preview.title} · ${preview.username || t("noUser")} · ${preview.site}`;
  el("preview-changes").textContent = t(preview.action === "update" ? "retained" : "created");
}
async function cancelPreview() {
  const token = preview?.preview_token;
  preview = null;
  reviewedDraft = null;
  if (token && currentState) {
    // The server holds a digest only; an unreachable cancellation expires naturally.
    await request("/save/cancel", { body: JSON.stringify({ preview_token: token }) }).catch(() => {});
  }
}
el("pair-form").addEventListener("submit", (event) => {
  event.preventDefault();
  void action(async () => {
    let sidecarUrl;
    try { sidecarUrl = normalizeAddress(el("sidecar-url").value); }
    catch { throw Object.assign(new Error(), { key: "addressError" }); }
    currentState = { sidecarUrl };
    setStatus("pairing");
    const pairingCode = el("pairing-code").value.trim();
    el("pairing-code").value = "";
    const body = await request("/pair", { headers: { "X-Vault-Browser-Pairing": pairingCode },
      body: JSON.stringify({ remember_connection: el("remember").checked }) });
    currentState = { sidecarUrl, browserToken: body.browser_token,
      ...(body.connection_key ? { connectionKey: body.connection_key } : {}) };
    await chrome.storage.session.set({ [stateKey]: currentState });
    await showMatches();
  });
});
el("retry").addEventListener("click", () => void action(() => showMatches()));
el("keep-open").addEventListener("click", () => void action(async () => {
  const tab = await samePage();
  await chrome.windows.create({
    url: chrome.runtime.getURL(`popup.html?tab=${tab.id}&lang=${language}`),
    type: "popup", width: 420, height: 720,
  });
  window.close();
}));
el("add").addEventListener("click", () => openDraft());
el("capture").addEventListener("click", () => void action(async () => {
  await request("/status", { body: "{}" });
  const result = await inject(vaultUnifiedFillInputs, { capture: true });
  if (result.reason !== "captured") { outcome(result); return; }
  const existing = matches.filter((entry) => entry.username === result.username);
  openDraft(existing.length === 1 ? existing[0] : null);
  el("save-username").value = result.username;
  el("save-password").value = result.password;
  setStatus("captured");
}));
el("save-target").addEventListener("change", () => {
  const entry = matches.find((item) => item.id === el("save-target").value);
  el("save-title").value = entry?.title || new URL(currentTab.url).hostname;
  if (entry) el("save-username").value = entry.username;
});
el("generate").addEventListener("click", () => void action(async () => {
  const stamp = epoch;
  const result = await request("/generate", { body: "{}" });
  if (stamp !== epoch) return;
  el("save-password").value = result.password;
  setStatus("generated");
}));
el("reveal").addEventListener("click", () => {
  const show = el("save-password").type === "password";
  el("save-password").type = show ? "text" : "password";
  el("reveal").textContent = t(show ? "hide" : "show");
  el("reveal").setAttribute("aria-pressed", String(show));
});
el("fill-new").addEventListener("click", () => void action(async () => {
  await request("/status", { body: "{}" });
  outcome(await inject(vaultUnifiedFillInputs, { ...draft(), newPassword: true }));
}));
el("save-form").addEventListener("submit", (event) => {
  event.preventDefault();
  void action(async () => {
    await samePage();
    const body = draft();
    const result = await request("/save/preview", { body: JSON.stringify(body) });
    preview = result;
    reviewedDraft = body;
    renderPreview();
    el("draft-fields").hidden = true;
    el("save-preview").hidden = false;
    el("confirmed").checked = false;
    requestAnimationFrame(() => { if (!el("save-preview").hidden) el("confirmed").focus(); });
    setStatus("reviewHeading");
  });
});
el("confirm-save").addEventListener("click", () => void action(async () => {
  if (!el("confirmed").checked) { setStatus("confirmRequired", true); return; }
  await samePage();
  try {
    await request("/save/apply", { body: JSON.stringify({ ...reviewedDraft,
      preview_token: preview.preview_token, confirm_save: true }) });
  } catch (error) {
    if (error.code === 0) error.key = "saveUnknown";
    if (error.code === 409) {
      await cancelPreview();
      el("save-preview").hidden = true;
      el("draft-fields").hidden = false;
    }
    throw error;
  }
  clearDraft();
  await showMatches("saved");
}));
el("edit-draft").addEventListener("click", () => void action(async () => {
  await cancelPreview();
  el("save-preview").hidden = true;
  el("draft-fields").hidden = false;
}));
el("cancel-save").addEventListener("click", () => void action(async () => {
  await cancelPreview();
  clearDraft();
  el("accounts").hidden = false;
  setStatus("cancelled");
}));
el("forget").addEventListener("click", () => void action(async () => {
  epoch += 1;
  clearDraft();
  if (currentState?.browserToken) {
    try { await request("/disconnect", { body: "{}" }, Boolean(currentState.connectionKey)); }
    catch (error) { if (error.code !== 401) { setStatus("forgetFailed", true); return; } }
  }
  await chrome.storage.session.remove(stateKey);
  currentState = null;
  matches = [];
  renderMatches();
  el("accounts").hidden = true;
  el("retry").hidden = true;
  el("forget").hidden = true;
  el("pair-form").hidden = false;
  setStatus("forgotten");
}));
el("language").addEventListener("change", () => { language = el("language").value; localize(); });
window.addEventListener("pagehide", () => { epoch += 1; clearDraft(); });

// Polling never touches the desktop idle timer. No plaintext drafts enter storage.
const healthTimer = setInterval(async () => {
  if (busy || checking || !currentState?.browserToken || !currentTab || !el("retry").hidden) return;
  checking = true;
  const stamp = epoch;
  try {
    await samePage();
    await request("/status", { body: "{}" });
  } catch (error) {
    if (stamp === epoch || error.key === "pageChanged") await authFailure(error);
  } finally { checking = false; }
}, 2000);
window.addEventListener("pagehide", () => clearInterval(healthTimer));
localize();
void action(async () => {
  const result = await chrome.storage.session.get(stateKey);
  currentState = result[stateKey] || null;
  if (!currentState) {
    el("pair-form").hidden = false;
    setStatus("pairHint");
    return;
  }
  el("forget").hidden = false;
  await showMatches();
});
