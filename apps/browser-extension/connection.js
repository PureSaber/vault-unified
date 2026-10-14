/* Shared by the extension popup and background worker. Never exposed to a page. */
const vaultBrowserConnection = (() => {
  const stateKey = "vaultUnifiedBrowserPairing";
  function normalizeAddress(value) {
    const url = new URL(value.trim());
    const path = url.pathname.replace(/\/+$/, "");
    if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname)
        || url.username || url.password || url.search || url.hash || (path && path !== "/api")) {
      throw Object.assign(new Error(), { key: "addressError" });
    }
    return url.origin;
  }
  async function post(state, path, options = {}, connection = false) {
    if (!state) throw Object.assign(new Error(), { key: "unpaired", code: 401 });
    const base = normalizeAddress(state.sidecarUrl);
    let response;
    try {
      response = await fetch(`${base}/api/browser${path}`, {
        method: "POST", ...options, signal: AbortSignal.timeout(8000), cache: "no-store",
        headers: { "Content-Type": "application/json",
          ...(connection ? { "X-Vault-Browser-Connection": state.connectionKey }
            : state.browserToken ? { "X-Vault-Browser-Token": state.browserToken } : {}), ...options.headers },
      });
    } catch { throw Object.assign(new Error(), { key: "unavailable", code: 0 }); }
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      let key = { 423: "locked", 401: "unpaired", 503: "trustUnavailable", 409: "changed" }[response.status] || "requestError";
      if (typeof body.detail === "string" && body.detail.includes("username already exists")) key = "duplicate";
      if (typeof body.detail === "string" && body.detail.includes("already has these details")) key = "unchanged";
      throw Object.assign(new Error(), { key, code: response.status });
    }
    return body;
  }
  async function read() {
    const result = await chrome.storage.session.get(stateKey);
    if (result[stateKey]) return result[stateKey];
    const identity = await vaultBrowserIdentity.read();
    return identity ? { deviceId: identity.deviceId, sidecarUrl: normalizeAddress(identity.sidecarUrl) } : null;
  }
  async function prove(state, action) {
    const identity = await vaultBrowserIdentity.read();
    if (!identity || identity.deviceId !== state?.deviceId) throw Object.assign(new Error(), { key: "unpaired", code: 401 });
    const challenge = await post(state, "/device/challenge", { body: JSON.stringify({ device_id: identity.deviceId, action }) });
    const signature = await vaultBrowserIdentity.sign(identity, challenge, action);
    return post(state, "/device/prove", { body: JSON.stringify({ device_id: identity.deviceId, action, challenge_id: challenge.challenge_id, signature }) });
  }
  async function discover(state) {
    if (!chrome.runtime.sendNativeMessage || !state) return;
    try {
      const response = await chrome.runtime.sendNativeMessage("org.vaultunified.desktop", { type: "discover", protocol: 1 });
      if (response?.protocol !== 1 || !response.base_url) return;
      const address = normalizeAddress(response.base_url);
      if (address !== state.sidecarUrl) {
        state.sidecarUrl = address; delete state.browserToken;
        if (state.deviceId) {
          const identity = await vaultBrowserIdentity.read();
          if (identity?.deviceId === state.deviceId) await vaultBrowserIdentity.save(identity, identity.deviceId, address);
        }
      }
    } catch { /* Keep the manual local address when discovery is unavailable. */ }
  }
  async function resume(state) {
    const result = state.deviceId ? await prove(state, "resume") : await post(state, "/resume", { body: "{}" }, true);
    state.browserToken = result.browser_token;
    await chrome.storage.session.set({ [stateKey]: state });
  }
  // Content scripts never receive this state or any access token.
  async function connectedRequest(path, body = {}) {
    const state = await read();
    if (!state) throw Object.assign(new Error(), { key: "unpaired", code: 401 });
    await discover(state);
    if (!state.browserToken) await resume(state);
    try { return await post(state, path, { body: JSON.stringify(body) }); }
    catch (error) {
      if (error.code !== 401 || !(state.deviceId || state.connectionKey)) throw error;
      await resume(state);
      return post(state, path, { body: JSON.stringify(body) });
    }
  }
  return { normalizeAddress, post, read, prove, discover, connectedRequest };
})();
