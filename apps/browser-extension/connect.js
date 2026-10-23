/* First connection approved in the desktop (docs/browser-connection-approval.md).
 * Runs in the service worker: the popup closes when the desktop takes focus, so
 * the pending request, its non-exportable key and poll secret live in IndexedDB.
 * The key becomes this browser's identity only after the desktop approves. */
const vaultBrowserConnect = (() => {
  const resultKey = "vaultUnifiedConnectResult";
  const pairingKey = "vaultUnifiedBrowserPairing"; // The state connection.js reads.
  const alarm = "vault-connect";
  let timer = null;
  let inflight = null;
  let starting = null;
  const fail = (key, code = 0) => { throw Object.assign(new Error(), { key, code }); };

  function browserName() {
    const brands = navigator.userAgentData?.brands?.map(brand => brand.brand) || [];
    const browser = brands.find(name => /Edge|Chrome|Brave|Opera|Vivaldi/.test(name) && !/Chromium/.test(name)) || "Chromium";
    const platform = navigator.userAgentData?.platform || "";
    return (platform ? `${browser} on ${platform}` : browser).slice(0, 64);
  }
  async function call(address, path, body, headers = {}) {
    let response;
    try {
      response = await fetch(`${address}/api/browser${path}`, {
        method: "POST", signal: AbortSignal.timeout(8000), cache: "no-store", body: JSON.stringify(body),
        headers: { "Content-Type": "application/json", "X-Vault-Extension-Version": chrome.runtime.getManifest().version, ...headers },
      });
    } catch { fail("connectUnavailable"); }
    const data = await response.json().catch(() => ({}));
    if (response.ok) return data;
    const code = typeof data?.detail === "object" ? data.detail.code : "";
    if (response.status === 426) fail("versionMismatch", 426);
    if (response.status === 423) fail("connectLocked", 423);
    if (response.status === 429) fail("connectBusy", 429);
    if (code === "device_limit") fail("connectDeviceLimit", 409);
    // An older desktop (no endpoint), a vault without device trust, or no nonce.
    if ([403, 404, 405].includes(response.status) || code === "upgrade_required") fail("connectManualOnly", response.status);
    fail("requestError", response.status);
  }
  function stop() {
    clearTimeout(timer); timer = null;
    void chrome.alarms?.clear(alarm);
  }
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => void poll().catch(() => {}), 2000);
    // A stopped worker resumes through the alarm (at most every 30 seconds).
    void chrome.alarms?.create(alarm, { periodInMinutes: 0.5 });
  }
  async function finish(state) {
    await vaultBrowserIdentity.removePending().catch(() => {});
    await chrome.storage.session.set({ [resultKey]: { state } });
    stop();
    return { state };
  }
  async function view() {
    const pending = await vaultBrowserIdentity.readPending().catch(() => null);
    if (pending) return { state: "waiting", code: pending.code };
    const stored = (await chrome.storage.session.get(resultKey))[resultKey];
    return stored ? { state: stored.state } : { state: "idle" };
  }
  async function begin() {
    const current = await view();
    if (current.state === "waiting") { schedule(); return current; }
    await chrome.storage.session.remove(resultKey);
    const identity = await vaultBrowserIdentity.create();
    let found, started;
    for (let attempt = 0; !started; attempt += 1) {
      found = await vaultBrowserConnection.locate();
      if (!found) fail("connectUnavailable");
      if (!found.nonce) fail("connectManualOnly");
      try {
        started = await call(found.address, "/connect/request", { public_key: identity.publicKey, device_name: browserName() },
          { "X-Vault-Connect-Nonce": found.nonce });
      } catch (error) {
        // A nonce from before a desktop restart: discover once more.
        if (error.code !== 403 || attempt) throw error;
      }
    }
    if (!/^\d{6}$/.test(started.code || "") || typeof started.request_id !== "string" || typeof started.poll_secret !== "string") fail("requestError");
    await vaultBrowserIdentity.savePending(identity, { requestId: started.request_id, pollSecret: started.poll_secret, code: started.code,
      expiresAt: Date.now() + Number(started.expires_in_seconds || 120) * 1000, sidecarUrl: found.address });
    schedule();
    return { state: "waiting", code: started.code };
  }
  async function check() {
    const pending = await vaultBrowserIdentity.readPending();
    if (!pending) { stop(); return view(); }
    let result;
    try {
      result = await call(pending.sidecarUrl, "/connect/status", { request_id: pending.requestId, poll_secret: pending.pollSecret });
    } catch (error) {
      // Unknown means expired (or already reported); anything else is retried until well past expiry.
      if (error.code === 404 || Date.now() > pending.expiresAt + 150_000) return finish("expired");
      schedule();
      return { state: "waiting", code: pending.code };
    }
    if (result.state === "pending") { schedule(); return { state: "waiting", code: pending.code }; }
    if (result.state === "approved" && /^[a-f0-9]{32}$/.test(result.device_id || "")) {
      await vaultBrowserIdentity.save({ privateKey: pending.privateKey, publicKey: pending.publicKey }, result.device_id, pending.sidecarUrl);
      // The token still comes from the normal signed resume; none is stored here.
      await chrome.storage.session.set({ [pairingKey]: { deviceId: result.device_id, sidecarUrl: pending.sidecarUrl } });
      return finish("approved");
    }
    return finish(["denied", "expired", "locked", "device_limit"].includes(result.state) ? result.state : "failed");
  }
  // Two popup windows clicking Connect share one request.
  function start() {
    starting ||= begin().finally(() => { starting = null; });
    return starting;
  }
  function poll() {
    inflight ||= check().finally(() => { inflight = null; });
    return inflight;
  }
  async function cancel() {
    await vaultBrowserIdentity.removePending().catch(() => {});
    await chrome.storage.session.remove(resultKey);
    stop();
    return { state: "idle" };
  }
  async function acknowledge() {
    await chrome.storage.session.remove(resultKey);
    return { state: "idle" };
  }
  return { start, poll, view, cancel, acknowledge, alarm };
})();
