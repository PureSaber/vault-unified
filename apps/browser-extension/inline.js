(() => {
  if (globalThis.__vaultUnifiedInlineInstalled) return;
  globalThis.__vaultUnifiedInlineInstalled = true;
  let target = null, host = null, shadow = null, pending = null, timer = null, version = 0;
  let language = navigator.language.toLowerCase().startsWith("zh") ? "zh" : "en";
  const text = (zh, en) => language === "zh" ? zh : en;
  const visible = input => input instanceof HTMLInputElement && input.isConnected && !input.disabled && !input.readOnly
    && input.getBoundingClientRect().width > 0 && input.getBoundingClientRect().height > 0
    && getComputedStyle(input).visibility === "visible" && getComputedStyle(input).opacity !== "0";
  const kind = input => !visible(input) || input.autocomplete.toLowerCase() === "new-password" ? null
    : input.autocomplete.toLowerCase() === "one-time-code" ? "otp"
    : input.type === "password" ? "password" : ["text", "email", "tel"].includes(input.type) ? "username" : null;
  const request = message => chrome.runtime.sendMessage(message);
  function close() { ++version; clearTimeout(timer); host?.remove(); host = null; shadow = null; pending = null; }
  function locate() {
    if (!host || !visible(target)) { close(); return; }
    const box = target.getBoundingClientRect();
    const width = host.dataset.picker === "true" ? Math.min(340, innerWidth - 16) : 36;
    host.style.setProperty("left", `${Math.max(8, Math.min(innerWidth - width - 8, box.right - width))}px`, "important");
    host.style.setProperty("top", `${Math.max(8, Math.min(innerHeight - host.getBoundingClientRect().height - 8, host.dataset.picker === "true" ? box.bottom + 4 : box.top + 3))}px`, "important");
  }
  function createHost(picker) {
    host?.remove();
    host = document.createElement("div"); host.dataset.picker = String(picker);
    host.style.cssText = "all:initial!important;position:fixed!important;display:block!important;z-index:2147483647!important;";
    shadow = host.attachShadow({ mode: "closed" });
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(`:host{color-scheme:light dark} *{box-sizing:border-box} .panel{width:min(340px,calc(100vw - 16px));max-height:min(360px,calc(100vh - 16px));overflow:auto;background:#151b24;color:#e7ecf3;border:1px solid #62738b;border-radius:8px;padding:10px;font:14px/1.5 system-ui;box-shadow:0 3px 14px #0006} button{font:14px/1.5 system-ui;background:#243044;color:#e7ecf3;border:1px solid #62738b;border-radius:5px;padding:8px;cursor:pointer} button:focus-visible{outline:3px solid #69b6ff;outline-offset:1px} button:disabled{opacity:.6;cursor:wait} .badge{width:32px;height:28px;padding:1px;font-weight:bold} .account{display:block;width:100%;margin:6px 0;text-align:left} strong,small{display:block;overflow-wrap:anywhere} small{color:#c5d0de} p{margin:4px 0 8px;overflow-wrap:anywhere} .footer{margin-top:8px}`);
    shadow.adoptedStyleSheets = [sheet]; document.documentElement.append(host);
    locate();
  }
  function errorText(error) {
    if (error === "siteDisabled") return text("请在扩展中开启此网站。", "Enable this website in the extension.");
    if (error === "locked") return text("请先解锁桌面密码库，然后重试。", "Unlock the desktop vault, then try again.");
    if (error === "unpaired") return text("请打开扩展完成配对。", "Open the extension to pair this browser.");
    if (["targetChanged", "pageChanged"].includes(error)) return text("页面或输入框已改变，请重新选择。", "The page or field changed. Choose again.");
    return text("未能填充，请打开扩展检查连接后重试。", "Could not fill. Check the connection in the extension and retry.");
  }
  function plan() {
    const mode = kind(target);
    if (!mode) return null;
    const form = target.form;
    const scope = form || target.getRootNode();
    const fields = [...scope.querySelectorAll("input")].filter(visible);
    const usernames = fields.filter(input => ["text", "email", "tel"].includes(input.type) && ["username", "email"].includes(input.autocomplete.toLowerCase()));
    const passwords = fields.filter(input => input.type === "password" && input.autocomplete.toLowerCase() !== "new-password");
    if (mode === "otp") return { mode, otp: target, form };
    if (mode === "username") return form && passwords.length === 1 && !fields.some(input => input.autocomplete.toLowerCase() === "new-password")
      ? { mode: "login", username: target, password: passwords[0], form } : { mode, username: target, form };
    return form && usernames.length === 1 ? { mode: "login", password: target, username: usernames[0], form } : { mode, password: target, form };
  }
  function deliver(message) {
    const selection = pending;
    if (!selection || message.nonce !== selection.nonce || message.origin !== location.origin || Date.now() >= selection.expires) return { filled: false };
    pending = null;
    const fields = [selection.username, selection.password, selection.otp].filter(Boolean);
    if (!fields.every(input => visible(input) && input.form === selection.form) || target !== selection.target) return { filled: false };
    if (selection.password && kind(selection.password) !== "password") return { filled: false };
    if (selection.otp && (!/^\d{6}(\d{2})?$/.test(message.values.otp || "") || Date.now() >= message.values.expiresAt
        || (selection.otp.maxLength > 0 && selection.otp.maxLength < message.values.otp.length))) return { filled: false };
    const values = message.values;
    if (selection.password && !values.password) return { filled: false };
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    // Validate every chosen element before changing any value. Never submit.
    for (const field of ["username", "password", "otp"]) if (selection[field] && typeof values[field] === "string") {
      if (version !== selection.version || target !== selection.target || !visible(selection[field])
          || (field === "password" && kind(selection[field]) !== "password")) return { filled: false };
      setter.call(selection[field], values[field]);
      selection[field].dispatchEvent(new Event("input", { bubbles: true, composed: true }));
      selection[field].dispatchEvent(new Event("change", { bubbles: true, composed: true }));
    }
    close(); return { filled: true };
  }
  async function choose(entry, status, buttons) {
    const selection = plan();
    if (!selection) { status.textContent = errorText("targetChanged"); return; }
    const stamp = version;
    const nonce = crypto.randomUUID();
    pending = { ...selection, target, nonce, version, expires: Date.now() + 60_000 };
    buttons.forEach(button => { button.disabled = true; });
    clearTimeout(timer); timer = setTimeout(close, 60_000);
    try {
      const result = await request({ type: "vault-inline-select", entryId: entry.id, nonce, mode: selection.mode });
      if (stamp !== version) return;
      if (result.error) { pending = null; status.textContent = errorText(result.error); buttons.forEach(button => { button.disabled = false; }); }
      else if (result.confirmation) status.textContent = text("请在扩展确认窗口核对内嵌网站。", "Review the embedded website in the extension confirmation window.");
    } catch { if (stamp === version) { pending = null; status.textContent = errorText(); buttons.forEach(button => { button.disabled = false; }); } }
  }
  async function openPicker() {
    if (!kind(target)) return;
    close(); createHost(true);
    const stamp = version;
    const panel = document.createElement("section"); panel.className = "panel"; panel.setAttribute("aria-label", text("Vault Unified 账号选择", "Vault Unified account picker"));
    const heading = document.createElement("strong"); heading.textContent = "Vault Unified";
    const origin = document.createElement("small"); origin.textContent = location.origin;
    const status = document.createElement("p"); status.setAttribute("role", "status"); status.textContent = text("正在查找账号…", "Finding accounts…");
    const rows = document.createElement("div");
    const dismiss = document.createElement("button"); dismiss.type = "button"; dismiss.className = "footer"; dismiss.textContent = text("关闭", "Close");
    dismiss.addEventListener("click", event => { if (event.isTrusted) { close(); target?.focus(); } });
    panel.append(heading, origin, status, rows, dismiss); shadow.append(panel); locate(); timer = setTimeout(close, 30_000);
    try {
      const result = await request({ type: "vault-inline-matches" });
      if (stamp !== version) return;
      if (result.error) { status.textContent = errorText(result.error); return; }
      language = result.language;
      const entries = result.matches.filter(entry => kind(target) !== "otp" || entry.has_totp).sort((a, b) => Number(b.id === result.preferred) - Number(a.id === result.preferred)).slice(0, 20);
      status.textContent = entries.length ? text("选择账号填入当前表单。不会自动提交。", "Choose an account for this form. It will not submit.") : text("此网站没有匹配的账号。", "No matching accounts for this website.");
      const buttons = [];
      for (const entry of entries) {
        const button = document.createElement("button"); button.type = "button"; button.className = "account";
        const title = document.createElement("strong"); title.textContent = entry.title;
        const user = document.createElement("small"); user.textContent = entry.username || text("无用户名", "No username");
        button.append(title, user); button.addEventListener("click", event => { if (event.isTrusted) void choose(entry, status, buttons); });
        buttons.push(button); rows.append(button);
      }
      panel.addEventListener("keydown", event => {
        if (!event.isTrusted || !["ArrowDown", "ArrowUp"].includes(event.key) || !buttons.length) return;
        event.preventDefault(); const index = buttons.indexOf(shadow.activeElement);
        buttons[index < 0 ? (event.key === "ArrowDown" ? 0 : buttons.length - 1) : (index + (event.key === "ArrowDown" ? 1 : buttons.length - 1)) % buttons.length].focus();
      });
      buttons[0]?.focus(); locate();
    } catch { if (stamp === version) status.textContent = errorText(); }
  }
  async function showButton(input) {
    close(); target = input;
    if (!kind(input)) return;
    const stamp = version;
    try {
      const result = await request({ type: "vault-inline-check" });
      if (stamp !== version || result.error || !result.enabled || !kind(input)) return;
      language = result.language; createHost(false);
      const button = document.createElement("button"); button.type = "button"; button.className = "badge"; button.textContent = "V";
      button.setAttribute("aria-label", text("从 Vault Unified 选择账号", "Choose account from Vault Unified"));
      button.addEventListener("click", event => { if (event.isTrusted) void openPicker(); }); shadow.append(button); locate();
    } catch { /* Unavailable/removed extension leaves the ordinary field untouched. */ }
  }
  document.addEventListener("focusin", event => {
    if (!event.isTrusted || event.composedPath().includes(host)) return;
    const input = event.composedPath()[0];
    if (input instanceof HTMLInputElement && kind(input)) void showButton(input);
    else close();
  }, true);
  document.addEventListener("keydown", event => { if (event.isTrusted && event.key === "Escape" && host) { event.preventDefault(); close(); target?.focus(); } }, true);
  document.addEventListener("pointerdown", event => { if (host && !event.composedPath().includes(host) && event.composedPath()[0] !== target) close(); }, true);
  window.addEventListener("scroll", locate, true); window.addEventListener("resize", locate);
  window.addEventListener("pagehide", close);
  chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (sender.id !== chrome.runtime.id) return false;
    if (message.type === "vault-inline-deliver") { respond(deliver(message)); return false; }
    if (message.type === "vault-inline-reset") { close(); if (kind(document.activeElement)) void showButton(document.activeElement); respond({ done: true }); }
    if (message.type === "vault-inline-open" && document.hasFocus() && kind(target)) { void openPicker(); respond({ opened: true }); }
    return false;
  });
  if (kind(document.activeElement)) void showButton(document.activeElement);
})();
