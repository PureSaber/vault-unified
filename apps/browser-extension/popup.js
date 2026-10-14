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
  versionMismatch: ["桌面与扩展版本不一致，请更新同一安装套件中的两个组件后重试。", "Desktop and extension versions differ. Update both from the same release kit and retry."],
  fillOtp: ["填入验证码", "Fill verification code"],
  otpFilled: ["已填入验证码。", "Verification code filled."],
  otpAmbiguous: ["未找到唯一的验证码输入框，可从桌面端复制后粘贴。", "No single verification-code field was found. Copy the code from the desktop."],
  otpExpired: ["验证码已过期，请重新填充。", "The verification code expired. Fill again."],
  language: ["语言", "Language"], address: ["本机地址", "Local address"],
  code: ["一次性配对码", "One-time pairing code"], pair: ["配对此浏览器", "Pair this browser"],
  remember: ["授权此浏览器在重启后恢复连接（仍需解锁保险库）。", "Authorize this browser to reconnect after restarting (vault must be unlocked)."],
  deviceName: ["浏览器名称", "Browser name"],
  trustUnavailable: ["无法保存设备授权。请检查 Windows 凭据管理器，或取消勾选长期授权后重试。", "Could not save device authorization. Check Windows Credential Manager, or uncheck authorization and pair for this session."],
  identityUnavailable: ["浏览器身份存储不可用。可取消长期授权，仅为本次会话配对。", "Browser identity storage is unavailable. Uncheck authorization to pair for this session only."],
  newAddress: ["若桌面端地址已改变，请填写新的本机地址", "If the desktop address changed, enter its new local address"],
  updateAddress: ["更新地址并重新连接", "Update address and reconnect"],
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
  generatedRecoverable: ["新密码已加入桌面生成历史；确认保存后才会更新账号。", "Password kept in desktop generation history; confirm Save to update the account."],
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
  return vaultBrowserConnection.normalizeAddress(value);
}
async function request(path, options = {}, connection = false) {
  const stamp = epoch;
  const body = await vaultBrowserConnection.post(currentState, path, options, connection);
  if (stamp !== epoch) throw Object.assign(new Error(), { key: "locked", code: 423 });
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
  const remembered = Boolean(currentState?.connectionKey || currentState?.deviceId);
  if (!currentState?.browserToken && !remembered) currentState = null;
  if (error.code === 401 && !remembered) {
    await chrome.storage.session.remove(stateKey);
    currentState = null;
  }
  el("pair-form").hidden = Boolean(currentState);
  el("retry").hidden = !currentState;
  el("retry-address-form").hidden = !currentState?.deviceId;
  if (currentState) el("retry-address").value = currentState.sidecarUrl;
  el("forget").hidden = !currentState;
  setStatus(remembered && error.code === 401 ? "locked" : error.key || "requestError", true);
}
async function action(work) {
  if (busy) return;
  busy = true;
  document.querySelectorAll("button,input,select").forEach((node) => { node.disabled = true; });
  try { await work(); }
  catch (error) {
    if ([0, 401, 423, 503].includes(error.code)) await authFailure(error);
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
  if (result.reason?.startsWith("otp-")) {
    setStatus({ "otp-filled": "otpFilled", "otp-expired": "otpExpired" }[result.reason] || "otpAmbiguous", result.reason !== "otp-filled");
    return;
  }
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
async function fillOtp(entry) {
  const stamp = epoch;
  await samePage();
  const started = Date.now();
  const value = await request("/totp", { body: JSON.stringify({ entry_id: entry.id, url: new URL(currentTab.url).origin }) });
  if (stamp !== epoch) return;
  const validForMs = value.remaining_seconds * 1000 - (Date.now() - started);
  if (validForMs <= 0) { setStatus("otpExpired", true); return; }
  outcome(await inject(vaultUnifiedFillInputs, { otp: value.code, expiresAt: Date.now() + validForMs }));
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
    if (entry.has_totp) {
      const otp = document.createElement("button");
      otp.type = "button"; otp.className = "secondary"; otp.textContent = t("fillOtp");
      otp.setAttribute("aria-label", `${t("fillOtp")} ${entry.title}`);
      otp.addEventListener("click", () => void action(() => fillOtp(entry)));
      row.append(otp);
    }
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
  await discoverDesktop();
  const path = `/matches?url=${encodeURIComponent(new URL(tab.url).origin)}`;
  let result;
  if (currentState.deviceId && !currentState.browserToken) await resumeTrusted();
  try { result = await request(path, { body: "{}" }); }
  catch (error) {
    if (error.code !== 401 || !(currentState?.connectionKey || currentState?.deviceId)) throw error;
    try {
      const resumed = currentState.deviceId ? await trustedProof("resume") : await request("/resume", { body: "{}" }, true);
      if (stamp !== epoch) return;
      currentState.browserToken = resumed.browser_token;
      await chrome.storage.session.set({ [stateKey]: currentState });
      result = await request(path, { body: "{}" });
    } catch (resumeError) {
      if (resumeError.code === 401) {
        await chrome.storage.session.remove(stateKey);
        if (currentState?.deviceId) await vaultBrowserIdentity.remove();
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
  el("retry-address-form").hidden = true;
  el("forget").hidden = false;
  setStatus(successKey || (matches.length ? "choose" : "noMatches"));
}
async function trustedProof(action) {
  const stamp = epoch;
  const result = await vaultBrowserConnection.prove(currentState, action);
  if (stamp !== epoch) throw Object.assign(new Error(), { key: "locked", code: 423 });
  return result;
}
async function resumeTrusted() {
  try {
    const resumed = await trustedProof("resume");
    currentState.browserToken = resumed.browser_token;
    await chrome.storage.session.set({ [stateKey]: currentState });
  } catch (error) {
    if (error.code === 401) {
      await chrome.storage.session.remove(stateKey);
      await vaultBrowserIdentity.remove();
      currentState = null;
    }
    throw error;
  }
}
async function discoverDesktop() {
  await vaultBrowserConnection.discover(currentState);
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
    const identity = el("remember").checked ? await vaultBrowserIdentity.create() : null;
    const body = await request("/pair", { headers: { "X-Vault-Browser-Pairing": pairingCode },
      body: JSON.stringify({ remember_connection: el("remember").checked,
        ...(identity ? { public_key: identity.publicKey, device_name: el("device-name").value.trim() || "Browser" } : {}) }) });
    if (identity && body.device_id) await vaultBrowserIdentity.save(identity, body.device_id, sidecarUrl);
    currentState = { sidecarUrl, browserToken: body.browser_token,
      ...(body.device_id ? { deviceId: body.device_id } : {}),
      ...(body.connection_key ? { connectionKey: body.connection_key } : {}) };
    await chrome.storage.session.set({ [stateKey]: currentState });
    await showMatches();
  });
});
el("retry").addEventListener("click", () => void action(() => showMatches()));
el("retry-address-form").addEventListener("submit", (event) => {
  event.preventDefault();
  void action(async () => {
    if (!currentState?.deviceId) return;
    let address;
    try { address = normalizeAddress(el("retry-address").value); }
    catch { throw Object.assign(new Error(), { key: "addressError" }); }
    currentState.sidecarUrl = address;
    delete currentState.browserToken;
    if (currentState.deviceId) {
      const identity = await vaultBrowserIdentity.read();
      if (identity?.deviceId === currentState.deviceId) await vaultBrowserIdentity.save(identity, identity.deviceId, address);
    }
    await chrome.storage.session.set({ [stateKey]: currentState });
    await showMatches();
  });
});
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
  const result = await request("/generate", { body: JSON.stringify({ url: new URL(currentTab.url).origin, request_id: crypto.randomUUID() }) });
  if (stamp !== epoch) return;
  el("save-password").value = result.password;
  setStatus(result.history_saved ? "generatedRecoverable" : "generated");
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
  if (currentState?.deviceId) {
    try { await trustedProof("revoke"); }
    catch (error) { if (error.code !== 401) { setStatus("forgetFailed", true); return; } }
    await vaultBrowserIdentity.remove();
  } else if (currentState?.browserToken) {
    try { await request("/disconnect", { body: "{}" }, Boolean(currentState.connectionKey)); }
    catch (error) { if (error.code !== 401) { setStatus("forgetFailed", true); return; } }
  }
  await chrome.storage.session.remove(stateKey);
  currentState = null;
  matches = [];
  renderMatches();
  el("accounts").hidden = true;
  el("retry").hidden = true;
  el("retry-address-form").hidden = true;
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
    try {
      const identity = await vaultBrowserIdentity.read();
      if (identity) currentState = { deviceId: identity.deviceId, sidecarUrl: normalizeAddress(identity.sidecarUrl) };
    } catch {
      el("remember").checked = false;
      el("pair-form").hidden = false;
      setStatus("identityUnavailable", true);
      return;
    }
  }
  if (!currentState) {
    el("pair-form").hidden = false;
    setStatus("pairHint");
    return;
  }
  el("forget").hidden = false;
  await showMatches();
});
