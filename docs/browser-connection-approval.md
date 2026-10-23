# Browser connection approval (design)

Status: **proposed design**, revised after independent security review;
implementation follows in a separate pull request. This document changes no
code or data format. It extends
[trusted browser connections](trusted-browser-connections.md).

## Goal

Everyday use should be:

1. Open and unlock Vault Unified.
2. A browser that was authorized before reconnects by itself.
3. Choose an account and fill the login form.

No routine copying of a local address or pairing code, and no automatic form
submission.

First use should be:

1. Click **Connect to Vault Unified** in the extension. It shows a 6-digit code.
2. Vault Unified comes forward and asks which code the browser shows. Pick the
   matching one of three. Nothing is typed or copied.
3. The authorization is remembered until it is revoked.

Manual pairing with the local address and one-time code stays available as a
recovery path under **Other ways to connect**.

## Current behavior, verified against `main` at 469902e

| Area | Current code | Consequence |
|---|---|---|
| Extension identity | `apps/browser-extension/manifest.json` has no `key`. | Chrome and Edge derive an unpacked extension's ID from its folder path, so the desktop cannot know the ID before pairing. |
| Native host registration | `browser_discovery.register(origin)` runs only inside `POST /api/browser/pair` (`api/routes/browser.py:83`). At startup, `restore_registration()` (`api/app.py:268`) only restores a manifest that already points to the same executable. | Before the first pairing, no host manifest lists the extension, so the browser refuses `sendNativeMessage`. |
| Who sets the host path | `apply_api_env` (`src-tauri/src/lib.rs:308`) sets `VAULT_BROWSER_HOST_EXE` for **every** Tauri build, debug builds included. | "The variable is set" does not mean "installed build". |
| First discovery | `discover()` in `connection.js:49` returns early when the extension has no saved state. | Even with a registered host, an unpaired extension never asks for the address. |
| Connect UI | Pairing runs in the action popup (`popup.js:324`), and a new key lives only in popup memory until `/pair` answers. | Chromium closes an action popup when it loses focus, so any flow that sends the user to the desktop must not live in the popup. |
| Enrollment | `browser_pairings.pair()` consumes a one-time code bound to the unlocked desktop session, then calls `browser_trust.enroll(binding, origin, public_key, device_name)` (`browser_pairing.py:144`). At most 16 devices (`browser_trust.py:29`). | Device trust, vault binding and the non-exportable signing key already exist. Only *starting* enrollment needs copying. |
| Reconnection | `connectedRequest()` runs `discover()`, then `resume()` with a signed single-use challenge (`/device/challenge`, `/device/prove`). | Reconnection is already automatic once a device is enrolled. |
| Locked vault | `trusted_resume` raises `BrowserLockedError`; `/device/challenge` answers `423` while locked, for a caller that names an enrolled device and origin. | Preserved. Today an unauthenticated caller without a device ID cannot learn the lock state. |
| Request guard | `sidecar_security_guard` (`api/app.py:129`) exempts named browser endpoints from the bootstrap secret; everything else needs it. | New endpoints must be placed explicitly. |
| Discovery endpoint | `GET /api/browser/discovery` is unauthenticated and returns `instance_id`. | `instance_id` is not a secret. |
| Desktop approvals | `PasskeyRequests.tsx` polls `GET /api/passkeys/pending` with the session token and calls `show_desktop_approval`. | Reused for polling and bringing the window forward **only**. Two differences: passkey approval also requires the master password (`PasskeyRequests.tsx:51`), and its requester already holds a browser token. A connect request comes from an unauthenticated caller, so it needs the stronger checks below. |

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
desktop (`browser_discovery.EXTENSION_ORIGINS`). There is no runtime override:
tests load the same unpacked extension and therefore get the same ID.

- Only the **public** key is kept. The private key matters only for packing a
  `.crx`; discarding it rules out a self-hosted or policy-installed `.crx` with
  this ID. A future Chrome Web Store or Edge Add-ons listing gets a
  store-assigned ID, which would be added to the allowlist then.
- **What the ID proves:** that a native-messaging caller is an extension with
  this ID in that browser profile. It proves nothing about an HTTP `Origin`
  header, which any local process can set. Anyone can also copy the public key
  into another unpacked extension, but the user must install it in Developer
  mode, and two extensions with one ID cannot be loaded together. **The trust
  anchor is the explicit desktop approval with number matching (section 5),
  not the ID.**

### 2. Native host registration at desktop start

The Tauri shell asks the API to register the fixed origin at startup only in
release builds (`!cfg!(debug_assertions)`); debug and portable development
builds never take over the shared HKCU key. Registration reuses `register()`,
its file format and HKCU keys, with these rules:

- **Never take over another installation:** if `native-host.json` points to a
  different executable that still exists, leave it alone (the same rule as
  `restore_registration`).
- **Origins:** the fixed origin is always included. Path-derived origins are
  kept only while a device record still uses them, so the list stays within
  the 32-origin limit (at most 16 devices plus the fixed origins). Today
  `register()` fails above 32; the fixed origin must not be lost to that.
- Registration only lets the browser launch the host. Discovery still never
  opens a vault and never launches the app.

### 3. Per-run connect nonce (native messaging only)

Each API start creates a random 32-byte **connect nonce**. It is written next
to `runtime.json` in the discovery directory (`%LOCALAPPDATA%\VaultUnified\browser-bridge`,
or the `VAULT_DATA_DIR` equivalent) with an owner-only DACL, and is never
returned by `GET /api/browser/discovery`. The native host adds it to its reply
**only** after the `allowed_origins` check, so only an allowlisted extension in
the user's own browser, or a process already running as that Windows user,
can obtain it.

It is not authentication or decryption material: it only allows *asking* for a
connection dialog. It blocks callers from other Windows accounts, which share
`127.0.0.1` but cannot read the file. The module docstring's "no
authentication material" rule is updated to say exactly this.

### 4. Connect request (extension service worker → API)

`POST /api/browser/connect/request` with `{public_key, device_name}` and the
header `X-Vault-Connect-Nonce`.

- **Guard:** only `connect/request` and `connect/status` skip the bootstrap
  secret in `sidecar_security_guard`. `connect/pending`, `connect/approve`,
  `connect/deny` and `connect/deny-all` require the bootstrap secret **and** a
  desktop session Bearer token, like every other desktop endpoint.
- **Checks, in order:** exact allowlisted `Origin`; connect nonce compared
  with `hmac.compare_digest` (`403` otherwise, so only a nonce holder can learn
  whether the vault is unlocked); a vault is unlocked (`423` otherwise); the vault
  supports browser trust (a distinct `409 upgrade_required` for older payload
  formats, not "locked"); the binding has fewer than 16 devices
  (`409 device_limit`, shown as "Remove an unused browser in Vault Unified →
  Connections first").
- **Vault binding at creation:** the request records the browser binding of
  the live desktop sessions. If no session is live it is `423`; if live
  sessions disagree (not expected, since the desktop opens one vault), it is
  `409`.
- **Pending request:** a random request ID; a random poll secret returned only
  to the caller and stored as a SHA-256 digest; a 6-digit code from
  `secrets.randbelow(10**6)`, unique among pending requests; a 120-second
  expiry; the public key; and the device name.
- **Limits:** at most 3 pending requests in total and one per public key;
  at most 5 new requests per minute across all callers (`429`); and after
  **Deny all**, new requests are refused for 60 seconds. These only throttle
  noise; the protection against forged requests is section 5.

The extension creates its non-exportable ECDSA key exactly as persistent
pairing does today, but the whole flow runs in the **service worker**, not the
popup:

- The popup sends one runtime message; the worker discovers (now also without
  saved state), creates the key, sends the request and polls the status.
- The pending key, request ID, poll secret, code and expiry are stored in the
  extension's IndexedDB (the same database as the identity, a separate
  record). If the popup closes when the desktop takes focus, nothing is lost:
  reopening it shows the same code and state. If the worker is stopped, the
  next popup open or a `chrome.alarms` backstop resumes polling.
- Because enrollment happens only when the extension claims the result
  (section 6), a flow that is abandoned simply expires. No orphaned device
  record is created.

### 5. Desktop approval with number matching

The unlocked renderer polls `GET /api/browser/connect/pending` every 2 seconds
and shows one request at a time. It calls `show_desktop_approval` at most once
per request, and at most once every 10 seconds, so the window comes forward
without being pulled forward repeatedly.

The dialog does **not** show the correct code by itself. It shows three codes
in random order: the request's code and two random decoys that differ from
each other and from every pending code. The user picks the one the browser
shows. Nothing is typed.

| English | 中文 |
|---|---|
| Connect a browser to Vault Unified? | 要将浏览器连接到 Vault Unified 吗？ |
| Only continue if you just clicked **Connect to Vault Unified** in a browser. Choose the code that browser shows. | 仅当你刚刚在浏览器中点击了“连接到 Vault Unified”时才继续。请选择该浏览器显示的代码。 |
| Browser name (reported by the browser): Chrome on DESKTOP-1 | 浏览器名称（由浏览器提供）：Chrome on DESKTOP-1 |
| After you allow it, this browser can fill accounts from this vault whenever the vault is unlocked, until you revoke it in Connections. | 允许后，只要此保险库处于解锁状态，该浏览器即可填充其中的账号，直到你在“连接”中撤销。 |
| **482 913** · **105 377** · **730 264** | （同左，三个代码按钮） |
| None of these — Deny · Deny all | 都不是，拒绝 · 全部拒绝 |

- **Picking a code** calls `POST /api/browser/connect/approve` with
  `{request_id, code}`. The approving session must be live and have the same
  binding the request recorded. A wrong code **denies** the request: there is
  one attempt per request.
- **None of these — Deny** and **Escape** call `/deny`. **Deny all** (shown
  when more than one request is pending) calls `/deny-all` and starts the
  60-second refusal.
- **Who can approve:** a caller with the bootstrap secret and a live desktop
  session, which is the same bar as `POST /api/browser/pairing-code` today.
  The renderer is the intended holder. The bootstrap secret is also present in
  the sidecar's startup output to Tauri, and `/auth/unlock-keyring` can create
  a session for a bootstrap holder; such a caller can already enroll a browser
  through pairing today, so this adds no new capability. A master-password
  re-prompt is not required, because the person at the unlocked desktop
  already has full vault access.

### 6. Completion (extension claims the result)

The service worker polls `POST /api/browser/connect/status` with
`{request_id, poll_secret}` (allowlisted `Origin`, poll secret compared with
`compare_digest`):

- **pending:** the remaining time.
- **approved:** the server now calls `browser_trust.enroll()` with the binding
  recorded at approval, but only while a live session with that binding exists
  (otherwise the result is **locked**). It returns only `device_id`. The
  extension saves the identity as pairing does today, then performs the normal
  signed `resume`, which proves it holds the private key and issues the token
  through the existing path. No browser token is ever stored with a pending
  request.
- **denied / expired / locked:** shown once, then the request is gone.

A terminal status can be read only once; after that the request ID is unknown.
The extension shows:

| State | English | 中文 |
|---|---|---|
| Waiting | Approve in Vault Unified. Code: 482 913 | 请在 Vault Unified 中批准。代码：482 913 |
| Declined | Connection was declined. | 已拒绝连接。 |
| Expired | Request expired; try again. | 请求已过期，请重试。 |
| Locked | Unlock Vault Unified, then connect again. | 请解锁 Vault Unified 后重新连接。 |
| Too many | Too many requests; try again in a minute. | 请求过多，请一分钟后重试。 |
| Device limit | Remove an unused browser in Vault Unified → Connections first. | 请先在 Vault Unified →“连接”中移除不再使用的浏览器。 |
| Not available | This Vault Unified version needs manual pairing. | 此版本的 Vault Unified 需要手动配对。 |

The pending key is discarded unless the status is approved.

### 7. Clearing

The pending store uses the same hooks as `passkey_requests`:

- `SessionManager.lock(token)`: requests whose binding no longer has a live
  session are cleared.
- `lock_all()`: used by system lock/suspend, renderer reset, and restore or
  recovery apply; everything is cleared.
- Lazy idle expiry inside `SessionManager.get()`: treated like `lock(token)`.
- Disabling the browser bridge or revoking all devices also clears pending
  requests.

### 8. Unchanged

- The signed `resume` proof and its 60-second challenges.
- Tokens of at most 12 hours in `chrome.storage.session`.
- Desktop revocation, which also invalidates outstanding tokens.
- "Forget pairing" in the extension.
- Locked denial.
- No form submission.
- No account data over native messaging.

### 9. Implementation requirements from the second review

- **Lock order:** session manager → connect store, as in `passkey_requests`.
  The store never calls the session manager or the Windows credential store
  while holding its own lock.
- **Claim is idempotent and re-checked:** under the store lock, mark the
  request *claiming*; enroll outside the lock; then re-check. If a lock or
  "revoke all browsers" ended the request meanwhile, revoke the device that
  was just added and report **locked** or **denied**. Once enrolled, the
  poll-secret holder can re-read the same `device_id` until the claim
  deadline, so a lost response does not orphan the record.
- **Terminal states stay readable** (bounded, short-lived records), including
  **locked** after clearing on lock.
- **Choices are fixed per request** on the server; `/pending` returns the same
  three codes in the same order on every poll.
- **A wrong pick** starts the same 60-second refusal as Deny all, and the
  desktop shows "That code did not match. If you did not start this, someone
  else may be trying to connect." / "代码不匹配。如果不是你发起的，可能有其他程序在尝试连接。"
- **Rate-limit position:** only requests that pass the `Origin` and nonce
  checks count toward the 5-per-minute budget.
- **Device limit is global:** `enroll` counts records of every vault, so the
  request and the claim both check the global count and report
  `device_limit`. Records of another vault (or of a moved vault file) cannot be
  seen or revoked from the current vault; that is an existing limitation of
  pairing, recorded here and not changed by this design.
- **Nonce file:** created with an owner-only, non-inherited DACL from the start
  (not renamed from a temporary file that inherits the folder's access), with a
  permissions test.
- **Extension:** the `alarms` permission is added; the connect message is
  accepted only from the extension's own popup page, never from content
  scripts; the API's CORS allowed headers include `X-Vault-Connect-Nonce`; the
  claim window (120 seconds) exceeds the 30-second alarm period.
- **Tests:** the live journey registers its own unique host name, as
  `browser-trust-restart.mjs` does today; release-only startup registration is
  covered by unit tests and release acceptance.
- **Residual risk wording:** a user who habitually approves unexpected
  prompts is compromised after a few attempts. Number matching protects
  against confusion and prompt fatigue; it is not the barrier against a
  process already running as the same Windows user, which can enroll through
  existing paths without any prompt.

## Security analysis

| Threat | Mitigation |
|---|---|
| An unknown extension asks to connect | The browser refuses the native host unless the exact ID is in `allowed_origins`, so it cannot obtain the connect nonce; the API also rejects origins outside the allowlist; the user must still approve with number matching. |
| A process in another Windows account sends requests | It cannot read the connect nonce (owner-only file in the user's profile), so requests are rejected before any dialog appears. |
| A process running as the same Windows user forges a request | It can obtain the nonce and set any `Origin`. Its code is not shown in any browser, so a user who just clicked Connect finds no match and denies; a user who did not click Connect is told to continue only if they did. A user who picks blindly has a 1-in-3 chance per request, one attempt each, at most 5 requests a minute. A process with this level of access can already keylog the master password or tamper with the browser itself, so a fully compromised Windows account remains out of scope, as in the current threat model. |
| Approval while locked, or for another vault | Requests require an unlocked vault, record its binding, are cleared on lock, and approval requires a live session with the same binding. |
| Request flooding or dialog spam | 3 pending in total, one per key, 5 new per minute, 60-second refusal after Deny all, a 120-second expiry, one dialog at a time, and at most one window activation per request and per 10 seconds. A same-user process can still keep the queue full; that is a nuisance, not a bypass, and manual pairing does not use the queue. |
| Theft of the result | Only the poll-secret holder can read the status; it receives a `device_id`, not a token. A token still requires a signature from the private key that never left the extension. |
| Popup closes when the desktop takes focus | The flow runs in the service worker with pending state in IndexedDB; enrollment happens only when the extension claims it, so nothing is orphaned. |
| Another extension copies the public key | Requires the user to install it in Developer mode and remove the real one, as today; approval with number matching is still required. |

## Compatibility and migration

- **Browsers paired earlier** were enrolled with a path-derived origin. When the
  extension gains the fixed `key`, its ID changes, the stored identity no longer
  matches, and the extension offers **Connect to Vault Unified** for one
  approval. The old record can never revoke itself, because its key lived in
  the old ID's storage. Connections therefore labels it "Previous extension
  ID" / "旧扩展标识" and offers to revoke it. Old records count toward the
  16-device limit until they are revoked.
- **Older desktops** do not have the new endpoints, so a new extension shows
  "This Vault Unified version needs manual pairing" and offers manual pairing.
  **Older extensions** keep working with manual pairing.
- **No vault format change:** device records already live in Windows Credential
  Manager.

## Verification plan for the implementation

**Python**
- Guard placement: `request` and `status` without bootstrap; `pending`,
  `approve`, `deny`, `deny-all` rejected without bootstrap or Bearer.
- Origin allowlist, connect nonce, locked `423`, `upgrade_required`,
  `device_limit`, limits, rate limit and the Deny-all refusal.
- Number matching: the correct code approves, a wrong code denies, a second
  attempt is rejected.
- Binding recorded at creation and checked at approval and claim; clearing on
  `lock`, `lock_all` and idle expiry.
- Claim: enrollment only at claim, `device_id` only, terminal status readable
  once, poll secret checked with `compare_digest`.
- Startup registration: release-only flag, not overwriting another executable,
  fixed origin kept, unused path-derived origins pruned.
- The nonce never appears in `GET /api/browser/discovery`.

**Native host (Rust)**
- The nonce is returned only after the `allowed_origins` check.

**Renderer journeys (Chinese and English)**
- The approval dialog: correct pick, wrong pick, None of these, Escape, Deny
  all, expiry, lock while pending, window activation throttling, and
  accessibility.

**Extension journeys with a mock API**
- Connect states and their bilingual messages; closing and reopening the popup
  while waiting; resuming after the worker restarts.

**Live journeys** (actual native executable, Windows credential store,
Chromium, isolated profile, unique test host name)
1. The loaded extension's ID equals the constant.
2. First-contact discovery works without pairing and returns the nonce.
3. Approval by number matching, then filling.
4. Restart of both processes, then automatic reconnection.
5. Lock, denial, unlock, reconnection.
6. Rejection, including a wrong pick.
7. Revocation.
8. Recovery through manual pairing.

The full Chromium build Playwright uses for extensions does not start on the
development machine, so the live journeys rely on hosted CI. Physical checks in
the owner's real Chrome or Edge with the installed app remain release
acceptance, separate from automation.
