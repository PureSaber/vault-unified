/* Main world WebAuthn adapter. Origin and approval are enforced elsewhere. */
(() => {
  if (!window.isSecureContext || !navigator.credentials || !window.PublicKeyCredential || globalThis.__vaultPasskeyProvider) return;
  try { if (window.top.location.origin !== location.origin) return; } catch { return; }
  Object.defineProperty(globalThis, "__vaultPasskeyProvider", { value: true });
  const original = { create: navigator.credentials.create.bind(navigator.credentials), get: navigator.credentials.get.bind(navigator.credentials) };
  const b64 = window.btoa.bind(window), unb64 = window.atob.bind(window), clone = window.structuredClone.bind(window);
  const uuid = crypto.randomUUID.bind(crypto), channel = "vault-unified-passkeys-v1";
  function encode(value) {
    const bytes = ArrayBuffer.isView(value) ? new Uint8Array(value.buffer, value.byteOffset, value.byteLength) : new Uint8Array(value);
    if (!(value instanceof ArrayBuffer) && !ArrayBuffer.isView(value)) throw new TypeError();
    if (bytes.length > 1024) throw new TypeError();
    return b64(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }
  function decode(value) { return Uint8Array.from(unb64(value.replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0)).buffer; }
  function serialize(operation, value) {
    const result = { challenge: encode(value.challenge) };
    if (value.timeout !== undefined) result.timeout = value.timeout;
    if (value.extensions) {
      if (Object.keys(value.extensions).some(key => key !== "credProps")) throw new TypeError();
      result.extensions = clone(value.extensions);
    }
    const descriptors = values => values.map(item => ({ type: item.type, id: encode(item.id), ...(item.transports ? { transports: [...item.transports] } : {}) }));
    if (operation === "create") {
      result.rp = { name: String(value.rp.name), ...(value.rp.id === undefined ? {} : { id: value.rp.id }) };
      result.user = { id: encode(value.user.id), name: String(value.user.name), displayName: String(value.user.displayName) };
      result.pubKeyCredParams = value.pubKeyCredParams.map(item => ({ type: item.type, alg: item.alg }));
      if (value.authenticatorSelection) result.authenticatorSelection = clone(value.authenticatorSelection);
      if (value.excludeCredentials) result.excludeCredentials = descriptors(value.excludeCredentials);
    } else {
      if (value.rpId !== undefined) result.rpId = value.rpId;
      if (value.userVerification !== undefined) result.userVerification = value.userVerification;
      if (value.allowCredentials) result.allowCredentials = descriptors(value.allowCredentials);
    }
    if (JSON.stringify(result).length > 65536) throw new TypeError();
    return result;
  }
  function credential(value, operation) {
    const props = (target, fields) => {
      for (const [name, property] of Object.entries(fields)) Object.defineProperty(target, name, { enumerable: true, value: property });
      return target;
    };
    const wire = clone(value);
    const response = props(Object.create(operation === "create" ? AuthenticatorAttestationResponse.prototype : AuthenticatorAssertionResponse.prototype), {
      clientDataJSON: decode(wire.response.clientDataJSON),
      ...(operation === "create" ? { attestationObject: decode(wire.response.attestationObject),
        getAuthenticatorData: () => decode(wire.response.authenticatorData), getPublicKey: () => decode(wire.response.publicKey),
        getPublicKeyAlgorithm: () => wire.response.publicKeyAlgorithm, getTransports: () => [...wire.response.transports] }
        : { authenticatorData: decode(wire.response.authenticatorData), signature: decode(wire.response.signature), userHandle: decode(wire.response.userHandle) }),
    });
    return props(Object.create(PublicKeyCredential.prototype), { id: wire.id, rawId: decode(wire.rawId), type: "public-key", response,
      authenticatorAttachment: wire.authenticatorAttachment, getClientExtensionResults: () => clone(wire.clientExtensionResults), toJSON: () => clone(wire) });
  }
  function exchange(operation, options, signal) {
    return new Promise((resolve, reject) => {
      const id = uuid(); let timer, ackTimer;
      const cleanup = () => { clearTimeout(timer); clearTimeout(ackTimer); window.removeEventListener("message", receive); signal?.removeEventListener("abort", abort); };
      const cancel = () => window.postMessage({ channel, action: "cancel", id }, location.origin);
      const abort = () => { cleanup(); cancel(); reject(new DOMException("Passkey request aborted", "AbortError")); };
      function receive(event) {
        if (event.source !== window || event.origin !== location.origin || event.data?.channel !== channel || event.data.id !== id) return;
        if (event.data.action === "ack") { clearTimeout(ackTimer); return; }
        if (event.data.action !== "result") return;
        cleanup(); resolve(event.data.result);
      }
      if (signal?.aborted) { abort(); return; }
      window.addEventListener("message", receive); signal?.addEventListener("abort", abort, { once: true });
      ackTimer = setTimeout(() => { cleanup(); cancel(); resolve({ status: "fallback" }); }, 1000);
      timer = setTimeout(() => { cleanup(); cancel(); reject(new DOMException("Passkey request timed out", "NotAllowedError")); }, Math.min(Number(options.timeout) || 120000, 120000));
      window.postMessage({ channel, action: "begin", id, operation, options }, location.origin);
    });
  }
  for (const operation of ["create", "get"]) Object.defineProperty(navigator.credentials, operation, { configurable: true, writable: true, value: async options => {
    if (!options?.publicKey || options.mediation === "conditional" || options.mediation === "silent") return original[operation](options);
    let serialized;
    try { serialized = serialize(operation, options.publicKey); } catch { return original[operation](options); }
    const result = await exchange(operation, serialized, options.signal);
    if (result?.status === "fallback") return original[operation](options);
    if (result?.status === "excluded") throw new DOMException("A Passkey already exists for this account", "InvalidStateError");
    if (result?.status !== "complete") throw new DOMException("Passkey request cancelled", "NotAllowedError");
    return credential(result.credential, operation);
  } });
})();
