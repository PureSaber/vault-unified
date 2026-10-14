(() => {
  if (!chrome.permissions?.request || !chrome.runtime?.sendMessage) return;
  const controls = document.getElementById("inline-controls");
  const field = document.getElementById("inline-site");
  const status = document.getElementById("inline-status");
  let tabId = null;
  const zh = () => document.getElementById("language").value === "zh";
  const labels = {
    "inline-heading": ["输入框内选择账号", "Choose accounts inside fields"],
    "inline-site-label": ["网站或内嵌网站地址", "Website or embedded website address"],
    "inline-hint": ["默认关闭。开启后，点击输入框旁的 V 选择账号；也可使用 Alt+Shift+V。", "Off by default. Enable it, then select V beside a field or press Alt+Shift+V."],
    "inline-enable-site": ["开启此网站", "Enable this website"],
    "inline-disable-site": ["停用此网站", "Disable this website"],
    "inline-enable-all": ["允许所有网站", "Allow all websites"],
    "inline-disable-all": ["关闭全部建议并撤销权限", "Disable all suggestions and revoke permissions"],
  };
  function localize() { for (const [id, values] of Object.entries(labels)) document.getElementById(id).textContent = values[zh() ? 0 : 1]; }
  function origin() {
    const value = new URL(field.value);
    if (!["http:", "https:"].includes(value.protocol) || value.username || value.password) throw new Error();
    return value.origin;
  }
  async function refresh() {
    try {
      const result = await chrome.runtime.sendMessage({ type: "vault-inline-status", origin: origin() });
      status.textContent = result.enabled ? (zh() ? "此网站已开启输入框建议。" : "Suggestions are enabled for this website.") : (zh() ? "此网站的输入框建议已关闭。" : "Suggestions are off for this website.");
    } catch { status.textContent = zh() ? "请输入有效的 http 或 https 网站地址。" : "Enter a valid http or https website address."; }
  }
  for (const action of ["enable-site", "disable-site", "enable-all", "disable-all"]) document.getElementById(`inline-${action}`).addEventListener("click", async () => {
    let site;
    try {
      site = origin();
      if (action.startsWith("enable")) {
        const url = new URL(site);
        const origins = action === "enable-all" ? ["http://*/*", "https://*/*"] : [`${url.protocol}//${url.hostname}/*`];
        // Request directly inside the click handler while the browser user gesture is active.
        if (!await chrome.permissions.request({ origins })) { status.textContent = zh() ? "未授予网站权限。" : "Website permission was not granted."; return; }
      }
      const result = await chrome.runtime.sendMessage({ type: "vault-inline-settings", action, origin: site, tabId, language: zh() ? "zh" : "en" });
      if (result.error) throw new Error();
      await refresh();
    } catch { status.textContent = zh() ? "设置未完成，请检查网站地址后重试。" : "Settings were not applied. Check the website address and retry."; }
  });
  field.addEventListener("change", () => void refresh());
  document.getElementById("language").addEventListener("change", () => { localize(); void refresh(); });
  localize();
  void selectedTab().then(tab => {
    if (!tab?.id || !/^https?:/.test(tab.url || "")) return;
    tabId = tab.id; field.value = new URL(tab.url).origin; controls.hidden = false; return refresh();
  });
})();
