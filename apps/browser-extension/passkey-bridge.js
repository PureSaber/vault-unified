/* Isolated world: forwards only the bounded WebAuthn request/result channel. */
(() => {
  if (globalThis.__vaultPasskeyBridge) return;
  globalThis.__vaultPasskeyBridge = true;
  const pending = new Set();
  window.addEventListener("message", event => {
    const message = event.data;
    if (event.source !== window || event.origin !== location.origin || message?.channel !== "vault-unified-passkeys-v1"
        || !/^[a-f0-9-]{36}$/.test(message.id || "")) return;
    if (message.action === "cancel") {
      if (pending.has(message.id)) void chrome.runtime.sendMessage({ type: "vault-passkey-cancel", id: message.id }).catch(() => {});
      return;
    }
    if (message.action !== "begin" || pending.has(message.id) || pending.size >= 4) return;
    try { if (JSON.stringify(message.options).length > 65536) return; } catch { return; }
    pending.add(message.id);
    window.postMessage({ channel: message.channel, action: "ack", id: message.id }, location.origin);
    chrome.runtime.sendMessage({ type: "vault-passkey-begin", id: message.id, operation: message.operation, options: message.options })
      .then(result => window.postMessage({ channel: message.channel, action: "result", id: message.id, result }, location.origin))
      .catch(() => window.postMessage({ channel: message.channel, action: "result", id: message.id, result: { status: "fallback" } }, location.origin))
      .finally(() => pending.delete(message.id));
  });
  window.addEventListener("pagehide", () => {
    for (const id of pending) void chrome.runtime.sendMessage({ type: "vault-passkey-cancel", id }).catch(() => {});
    pending.clear();
  });
})();
