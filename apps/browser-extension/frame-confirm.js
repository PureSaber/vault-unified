const requestId = new URL(location.href).searchParams.get("id");
let zh = navigator.language.toLowerCase().startsWith("zh"), done = false;
const node = id => document.getElementById(id);
const request = type => chrome.runtime.sendMessage({ type, id: requestId });
const errorText = () => zh ? "确认已过期或页面已改变，请返回输入框重新选择。" : "Confirmation expired or the page changed. Choose again in the field.";
node("cancel").addEventListener("click", async () => { done = true; await request("vault-frame-cancel").catch(() => {}); window.close(); });
node("approve").addEventListener("click", async () => {
  node("approve").disabled = true;
  try {
    const result = await request("vault-frame-approve");
    if (result.error || !result.filled) { node("status").textContent = errorText(); return; }
    done = true; window.close();
  } catch { node("status").textContent = errorText(); }
});
window.addEventListener("pagehide", () => { if (!done) void request("vault-frame-cancel").catch(() => {}); });
void request("vault-frame-info").then(result => {
  if (result.error) { node("status").textContent = errorText(); return; }
  zh = result.language === "zh";
  document.documentElement.lang = zh ? "zh-CN" : "en";
  node("heading").textContent = zh ? "确认内嵌网站" : "Confirm embedded website";
  node("explanation").textContent = zh ? "登录表单位于另一个网站中。请核对下面的填充目标。" : "This login form belongs to another website. Check the destination below.";
  node("parent-label").textContent = zh ? "当前页面" : "Open page";
  node("frame-label").textContent = zh ? "填充目标" : "Fill destination";
  node("account-label").textContent = zh ? "账号" : "Account";
  node("parent").textContent = result.topOrigin; node("frame").textContent = result.origin;
  node("account").textContent = `${result.title} · ${result.username || "—"}`;
  node("approve").textContent = zh ? "确认向此网站填充" : "Confirm fill into this website";
  node("cancel").textContent = zh ? "取消" : "Cancel";
  node("approve").disabled = false;
  setTimeout(() => { node("approve").disabled = true; node("status").textContent = errorText(); }, Math.max(0, result.expires - Date.now()));
}).catch(() => { node("status").textContent = errorText(); });
