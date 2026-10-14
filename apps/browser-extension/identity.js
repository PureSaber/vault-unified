/* Persistent identity only. Access credentials and vault contents stay in memory/session storage. */
const vaultBrowserIdentity = (() => {
  const databaseName = "vault-unified-browser-identity-v1";
  function open() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(databaseName, 1);
      request.onupgradeneeded = () => request.result.createObjectStore("identity");
      request.onerror = () => reject(new Error("Browser identity storage unavailable"));
      request.onblocked = () => reject(new Error("Browser identity storage unavailable"));
      request.onsuccess = () => resolve(request.result);
    });
  }
  async function transact(mode, operation) {
    const db = await open();
    try {
      return await new Promise((resolve, reject) => {
        const transaction = db.transaction("identity", mode);
        const request = operation(transaction.objectStore("identity"));
        transaction.oncomplete = () => resolve(request.result);
        transaction.onerror = transaction.onabort = () => reject(new Error("Browser identity storage unavailable"));
      });
    } finally { db.close(); }
  }
  const encode = (value) => btoa(String.fromCharCode(...new Uint8Array(value)));
  async function create() {
    const keys = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, false, ["sign", "verify"]);
    return { privateKey: keys.privateKey, publicKey: encode(await crypto.subtle.exportKey("spki", keys.publicKey)) };
  }
  async function save(identity, deviceId, sidecarUrl) {
    if (!/^[a-f0-9]{32}$/.test(deviceId) || identity.privateKey.extractable) throw new Error("Invalid browser identity");
    await transact("readwrite", (store) => store.put({ privateKey: identity.privateKey,
      publicKey: identity.publicKey, deviceId, sidecarUrl }, "current"));
  }
  const read = () => transact("readonly", (store) => store.get("current"));
  const remove = () => transact("readwrite", (store) => store.delete("current"));
  async function sign(identity, challenge, action) {
    const origin = `chrome-extension://${chrome.runtime.id}`;
    const expected = `VaultUnified browser authorization v1\n${action}\n${identity.deviceId}\n${origin}\n${challenge.challenge_id}`;
    if (challenge.message !== expected || !/^[A-Za-z0-9_-]{43}$/.test(challenge.challenge_id)) {
      throw new Error("Unexpected browser authorization challenge");
    }
    return encode(await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, identity.privateKey,
      new TextEncoder().encode(expected)));
  }
  return { create, save, read, remove, sign };
})();
