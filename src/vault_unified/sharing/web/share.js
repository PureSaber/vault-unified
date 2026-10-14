"use strict";
(() => {
  const $ = id => document.getElementById(id);
  const words = {
    en: { heading: "Shared item", intro: "Open the item to use one available view. It decrypts in this browser.", open: "Open shared item", hide: "Hide content", loading: "Opening…", unavailable: "This link is expired, revoked, used up or incomplete.", invalid: "The shared content could not be verified.", hidden: "Content hidden. Reopen the original link if you need another view.", expires: "Available until", copy: "Copy", copied: "Copied", copyFailed: "Copy failed. Select the value to copy it.", reveal: "Show value", username: "Username", password: "Password", url: "Website", notes: "Notes", title: "Title" },
    zh: { heading: "分享的内容", intro: "打开内容会消耗一次可用查看次数。内容在此浏览器中解密。", open: "打开分享内容", hide: "隐藏内容", loading: "正在打开…", unavailable: "链接已过期、撤销、用尽次数或不完整。", invalid: "未能验证分享内容。", hidden: "内容已隐藏。如需再次查看，请重新打开原链接。", expires: "有效期至", copy: "复制", copied: "已复制", copyFailed: "复制失败，请选中内容后复制。", reveal: "显示内容", username: "用户名", password: "密码", url: "网站", notes: "备注", title: "标题" },
  };
  let locale = navigator.language.startsWith("zh") ? "zh" : "en", timer, values = null, stopped = false, controller;
  const original = new URLSearchParams(location.hash.slice(1));
  let keyText = original.get("key"), capability = original.get("cap");
  original.delete("key"); original.delete("cap");
  history.replaceState(null, "", location.pathname);
  const id = location.pathname.split("/").pop();
  const decode = value => {
    if (typeof value !== "string" || !/^[A-Za-z0-9_-]+$/.test(value) || value.length > 17 * 1024 * 1024) throw new Error();
    return Uint8Array.from(atob(value.replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0));
  };
  function translate() {
    document.documentElement.lang = locale; $("language").value = locale;
    for (const name of ["heading", "intro", "open", "hide"]) $(name).textContent = words[locale][name];
  }
  function clear() {
    stopped = true; controller?.abort();
    clearTimeout(timer); values = null; keyText = null; capability = null;
    $("fields").replaceChildren(); $("item-title").textContent = ""; $("content").hidden = true;
    $("status").textContent = words[locale].hidden; $("open").disabled = true;
  }
  $("language").onchange = () => { locale = $("language").value; translate(); if (values) render(values); };
  $("hide").onclick = clear;
  document.addEventListener("visibilitychange", () => { if (document.hidden) clear(); });
  window.addEventListener("pagehide", clear);
  window.addEventListener("hashchange", () => { if (location.hash) location.reload(); });
  function render(value) {
    $("item-title").textContent = value.title;
    $("fields").replaceChildren();
    for (const [name, text] of Object.entries(value.fields)) {
      const dt = document.createElement("dt"), dd = document.createElement("dd"), span = document.createElement("span");
      dt.textContent = words[locale][name] || name;
      span.textContent = name === "password" ? "••••••••" : text;
      dd.append(span);
      if (name === "password") {
        const reveal = document.createElement("button"); reveal.type = "button"; reveal.textContent = words[locale].reveal;
        reveal.onclick = () => { span.textContent = text; reveal.remove(); }; dd.append(reveal);
      }
      const copy = document.createElement("button"); copy.type = "button"; copy.textContent = words[locale].copy;
      copy.setAttribute("aria-label", `${words[locale].copy} ${words[locale][name] || name}`);
      copy.onclick = async () => { try { await navigator.clipboard.writeText(text); $("status").textContent = words[locale].copied; } catch { $("status").textContent = words[locale].copyFailed; } };
      dd.append(copy); $("fields").append(dt, dd);
    }
    $("content").hidden = false;
  }
  $("open").onclick = async () => {
    if (stopped) return;
    controller = new AbortController();
    $("open").disabled = true; $("status").textContent = words[locale].loading;
    try {
      if (!crypto.subtle || !/^[a-f0-9]{32}$/.test(id) || decode(keyText).length !== 32 || decode(capability).length !== 32) throw new Error();
      const key = await crypto.subtle.importKey("raw", decode(keyText), "AES-GCM", false, ["decrypt"]);
      keyText = null;
      const response = await fetch(`/v1/shares/${id}/read`, { method: "POST", signal: controller.signal, cache: "no-store", credentials: "omit", referrerPolicy: "no-referrer", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ capability }) });
      capability = null;
      if (!response.ok) { $("status").textContent = words[locale].unavailable; return; }
      const wire = await response.json(), blob = decode(wire.blob);
      const plain = await crypto.subtle.decrypt({ name: "AES-GCM", iv: blob.slice(0, 12), additionalData: new TextEncoder().encode(`vault-unified:share:v1:${id}`), tagLength: 128 }, key, blob.slice(12));
      const value = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(plain));
      if (value.version !== 1 || value.id !== id || typeof value.title !== "string" || value.title.length > 1000
          || !Number.isSafeInteger(value.expires) || value.expires * 1000 <= Date.now() || !value.fields || Array.isArray(value.fields)
          || Object.entries(value.fields).some(([name, text]) => !["username", "password", "url", "notes"].includes(name) || typeof text !== "string")) throw new Error();
      if (stopped || document.hidden) return;
      values = value; render(value);
      $("status").textContent = `${words[locale].expires} ${new Date(value.expires * 1000).toLocaleString(locale)}`;
      timer = setTimeout(clear, Math.min(5 * 60 * 1000, value.expires * 1000 - Date.now()));
    } catch { if (!stopped) $("status").textContent = words[locale].invalid; keyText = null; capability = null; }
  };
  translate();
})();
