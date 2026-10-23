# Browser connection approval (design)

Status: **proposed design**; implementation follows in a separate pull request.
This document changes no code or data format. It extends
[trusted browser connections](trusted-browser-connections.md).

## Goal

Everyday use should be:

1. Open and unlock Vault Unified.
2. A browser that was authorized before reconnects by itself.
3. Choose an account and fill the login form.

No routine copying of a local address or pairing code, and no automatic form
submission.

First use should be:

1. Click **Connect to Vault Unified** in the extension.
2. Review that specific browser in the desktop app, compare a short code shown
   in both places, and approve.
3. The authorization is remembered until it is revoked.

Manual pairing with the local address and one-time code stays available as a
recovery path.

## Current behavior, verified against `main` at 469902e

| Area | Current code | Consequence |
|---|---|---|
| Extension identity | `apps/browser-extension/manifest.json` has no `key`. | Chrome and Edge derive an unpacked extension's ID from its folder path, so the desktop cannot know the ID before pairing. |
| Native host registration | `browser_discovery.register(origin)` runs only inside `POST /api/browser/pair` (`api/routes/browser.py`). `restore_registration()` only restores an existing manifest. | Before the first pairing, no host manifest lists the extension, so the browser refuses `sendNativeMessage`. |
| First discovery | `discover()` in `connection.js` returns early when the extension has no saved state. | Even with a registered host, an unpaired extension never asks for the address. |
| Enrollment | `browser_pairings.pair()` consumes a one-time code bound to the unlocked desktop session, then calls `browser_trust.enroll(binding, origin, public_key, device_name)`. | Device trust, vault binding and the non-exportable signing key already exist. Only *starting* enrollment needs copying. |
| Reconnection | `connectedRequest()` in `connection.js` runs `discover()`, then `resume()` with a signed single-use challenge (`/device/challenge`, `/device/prove`). | Reconnection is already automatic for the popup, inline picker and background requests once a device is enrolled. |
| Locked vault | `trusted_resume` raises `BrowserLockedError`; proofs cannot unlock. | Preserved unchanged. |
| Desktop approvals | `PasskeyRequests.tsx` polls `GET /api/passkeys/pending` with the session token and calls the native `show_desktop_approval` command to bring the window forward. | An existing, reviewed pattern for "extension asks, desktop decides". It is reused below. |

Chromium documentation confirms the two browser-side facts this design relies
on:

- The manifest
  [`key`](https://developer.chrome.com/docs/extensions/reference/manifest/key)
  keeps an extension's ID constant when it is loaded unpacked.
- For [native messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging),
  `allowed_origins` lists exact extension origins with no wildcards, and on
  Windows the browser passes the caller's origin to the host as the first
  argument.

## Design

### 1. Stable extension identity

Add a public `key` to `manifest.json`, so every unpacked copy in Chrome and
Edge has the same ID wherever it is extracted. The ID is a constant in the
desktop (`browser_discovery.EXTENSION_ORIGINS`), plus an explicit override for
isolated tests and development builds.

- Only the **public** key is needed. A private key matters only for packing a
  `.crx`, which this project does not distribute, so it is not retained.
- A future Chrome Web Store or Edge Add-ons listing gets a store-assigned ID,
  which would be added to the allowlist then.
- **What the ID proves:** that the request comes from an extension with this ID
  in that browser profile. Anyone can copy the public key into another
  unpacked extension, but the user must install it in Developer mode, and two
  extensions with one ID cannot be loaded together. That is the same strength
  as today's path-derived origin check. **The trust anchor is the explicit
  desktop approval with a matching code, not the ID.**

### 2. Native host registration at desktop start

When the installed desktop starts its API (`VAULT_BROWSER_HOST_EXE` is set), it
registers the current-user native host for the fixed extension origins. It
keeps previously paired origins, and uses the existing `register()` code, file
format, limits and HKCU keys. Registration only lets the browser launch the
host. Discovery still returns only `protocol`, `base_url` and `instance_id`,
never opens a vault and never launches the app.

### 3. Connect request (extension → API)

`POST /api/browser/connect/request` with `{public_key, device_name}`. The
extension creates its non-exportable ECDSA key exactly as persistent pairing
does today.

- **Exact identity:** the API accepts only allowlisted `Origin` values. Any
  other extension uses manual pairing.
- **Locked denial:** without an unlocked v3 vault it returns `423`, and stores
  and shows nothing.
- **Pending request:** a random request ID; a random poll secret returned only
  to the caller; a 6-digit code; a 120-second expiry; and the device name.
  The code is `SHA-256(server nonce ‖ request ID ‖ public key) mod 10⁶`.
  Because the nonce comes from the server, a forged concurrent request cannot
  choose a code that matches the one the real extension displays.
- **Limits:** at most 3 pending requests in total and one per public key, with
  a per-origin rate limit. All pending requests are cleared when the vault
  locks.

### 4. Desktop approval

The unlocked renderer polls `GET /api/browser/connect/pending` with the session
token, like `PasskeyRequests`, and shows one dialog at a time. It calls
`show_desktop_approval` so the window comes forward even when it is in the
tray.

| English | 中文 |
|---|---|
| Connect this browser to Vault Unified? | 允许此浏览器连接 Vault Unified？ |
| Approve only if the browser shows the same code: **482 913** | 仅当浏览器显示相同代码时才允许：**482 913** |
| The browser can then fill accounts from this vault whenever it is unlocked, until you revoke it in Connections. | 之后在此保险库解锁时，该浏览器即可填充账号，直到你在“连接”中撤销。 |
| Allow · Deny | 允许 · 拒绝 |

- **Allow** calls `POST /api/browser/connect/approve`. This calls
  `browser_trust.enroll()` with the **approving session's** vault binding and
  issues a browser token, exactly like `pair()`.
- **Deny** calls `/deny`. Escape or closing the dialog leaves the request
  pending until it expires.
- Approval needs the unlocked desktop session's token, which exists only in
  renderer memory. No other local process can approve. A master-password
  re-prompt is not required: the person at the unlocked desktop already has
  full vault access.

### 5. Completion (extension)

The extension shows the same code and the message "Approve in Vault Unified",
then polls `POST /api/browser/connect/status` with `{request_id, poll_secret}`:

- **approved:** saves the identity as pairing does today, then shows the
  matching accounts.
- **denied:** "Connection was declined" / "已拒绝连接".
- **expired:** "Request expired; try again" / "请求已过期，请重试".
- **locked:** "Unlock Vault Unified, then connect again" / "请解锁 Vault Unified 后重新连接".

The key is discarded unless the status is approved.

### 6. Unchanged

These stay as they are:

- The signed `resume` proof and its 60-second challenges.
- Tokens of at most 12 hours in `chrome.storage.session`.
- Desktop revocation, which also invalidates outstanding tokens.
- "Forget pairing" in the extension.
- Locked denial.
- No form submission.
- No account data over native messaging.
- No secrets in discovery files.

## Security analysis

| Threat | Mitigation |
|---|---|
| An unknown extension asks to connect | The browser refuses the native host unless the exact ID is in `allowed_origins`; the API rejects origins outside the allowlist; the user must still approve. |
| A local process forges `Origin` and submits a request | Its code cannot match the code the real extension displays, because of the server nonce. The user must explicitly approve and is told to compare codes. Residual risk: a user who approves without comparing. That is comparable to disclosing today's pairing code, and a fully compromised Windows account is already out of scope. |
| Approval while locked, or for another vault | Requests require an unlocked vault and are cleared on lock. Enrollment uses the approving session's binding. |
| Request flooding or dialog spam | 3 pending in total, one per key, a rate limit, a 120-second expiry, and one dialog at a time. |
| Token theft from the pending request | The token is returned only to the holder of the poll secret, over loopback. |
| Another extension copies the public key | Requires the user to install it in Developer mode and remove the real one, as today; approval is still required. |

## Compatibility and migration

- **Browsers paired earlier** were enrolled with a path-derived origin. When the
  extension gains the fixed `key`, its ID changes, the stored identity no longer
  matches, and the extension offers **Connect to Vault Unified** for one
  approval. The old device record stays listed until it is revoked, labelled
  "Previous extension ID" / "旧扩展标识".
- **Older desktops** do not have the new endpoints, so a new extension falls back
  to manual pairing. **Older extensions** keep working with manual pairing.
- **No vault format change:** device records already live in Windows Credential
  Manager.

## Verification plan for the implementation

**Python**
- Request lifecycle, the origin allowlist, locked denial, approve, deny,
  expiry, limits, and clearing on lock.
- Vault binding, revocation after approval, poll-secret checks, and code
  derivation.
- Startup registration of the fixed origin, including keeping existing origins.

**Renderer journeys (Chinese and English)**
- The approval dialog: allow, deny, expiry, lock while pending, and
  accessibility.

**Extension journeys with a mock API**
- The Connect states and their bilingual messages.

**Live journeys** (actual native executable, Windows credential store,
Chromium, isolated profile, unique test host name)
1. The loaded extension's ID equals the constant.
2. First-contact discovery works without pairing.
3. Approval, then filling.
4. Restart of both processes, then automatic reconnection.
5. Lock, denial, unlock, reconnection.
6. Rejection.
7. Revocation.
8. Recovery through manual pairing.

Physical checks in the owner's real Chrome or Edge with the installed app
remain release acceptance, separate from automation.
