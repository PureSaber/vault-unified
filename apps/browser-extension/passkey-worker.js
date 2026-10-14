/* Trusted worker boundary: page messages never choose a website origin. */
const passkeyPending = new Map();
async function handlePasskey(message, sender) {
  if (sender.id !== chrome.runtime.id || !Number.isInteger(sender.tab?.id) || typeof sender.documentId !== "string"
      || !/^[a-f0-9-]{36}$/.test(message.id || "")) return { status: "cancelled" };
  const key = `${sender.tab.id}:${sender.documentId}:${message.id}`;
  if (message.type === "vault-passkey-cancel") {
    const pending = passkeyPending.get(key);
    if (pending) {
      pending.cancelled = true;
      if (pending.requestId) void vaultBrowserConnection.connectedRequest("/passkeys/cancel", { request_id: pending.requestId }).catch(() => {});
    }
    return { status: "cancelled" };
  }
  if (!["create", "get"].includes(message.operation) || !message.options || JSON.stringify(message.options).length > 65536) return { status: "fallback" };
  if (passkeyPending.size >= 4 || [...passkeyPending.values()].some(value => !value.cancelled && value.documentId === sender.documentId)) return { status: "cancelled" };
  // Register before the first await so immediate AbortSignal cancellation wins.
  const pending = { documentId: sender.documentId, cancelled: false, requestId: "", accepted: false };
  passkeyPending.set(key, pending);
  try {
    if (!(await preferences()).passkeys) return { status: "fallback" };
    const context = await frameContext(sender);
    if (context.origin !== context.topOrigin) return { status: "fallback" };
    await stillCurrent(context);
    if (pending.cancelled) return { status: "cancelled" };
    pending.requestId = crypto.randomUUID();
    const result = await vaultBrowserConnection.connectedRequest("/passkeys/begin", { request_id: pending.requestId, operation: message.operation, origin: context.origin, options: message.options });
    if (result.status === "fallback") return result;
    if (!result.request_id) return { status: "fallback" };
    if (result.request_id !== pending.requestId) return { status: "cancelled" };
    pending.accepted = true;
    const deadline = Date.now() + Math.min(result.timeout_ms || 120000, 120000);
    while (!pending.cancelled && Date.now() < deadline) {
      await stillCurrent(context);
      if (!(await preferences()).passkeys) return { status: "cancelled" };
      const response = await vaultBrowserConnection.connectedRequest("/passkeys/status", { request_id: pending.requestId });
      await stillCurrent(context);
      if (pending.cancelled || !(await preferences()).passkeys) return { status: "cancelled" };
      if (response.status === "complete") return { status: "complete", credential: response.credential };
      if (["cancelled", "fallback", "excluded"].includes(response.status)) return { status: response.status };
      await new Promise(resolve => setTimeout(resolve, 400));
    }
    return { status: "cancelled" };
  } catch (error) {
    // A definite pre-approval validation rejection can use the browser provider.
    // Transport uncertainty may have created a request; cancel it and fail closed.
    return { status: !pending.cancelled && !pending.accepted && (!pending.requestId || error.code === 400 || error.code === 401 || error.code === 423) ? "fallback" : "cancelled" };
  }
  finally {
    passkeyPending.delete(key);
    if (pending.requestId) await vaultBrowserConnection.connectedRequest("/passkeys/cancel", { request_id: pending.requestId }).catch(() => {});
  }
}
