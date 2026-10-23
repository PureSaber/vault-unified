# Install the Vault Unified browser extension

This release asset is for Chrome or Edge on the same Windows computer as
Vault Unified. The extension is optional and the desktop vault must be
unlocked before pairing or filling.

1. Download `Vault-Unified-Browser-Extension-v<version>.zip` from the same
   GitHub release as the desktop installer.
2. Extract the ZIP to a folder you will keep. Do not select the ZIP itself.
3. Open `chrome://extensions` in Chrome or `edge://extensions` in Edge.
4. Turn on **Developer mode**, choose **Load unpacked**, and select the
   extracted folder containing `manifest.json`.
5. Open and unlock Vault Unified, open the extension popup and click
   **Connect to Vault Unified**. The popup shows a 6-digit code. Vault Unified
   comes forward and shows three codes: choose the one the browser shows.
   Nothing is typed or copied. From then on the browser reconnects by itself
   whenever this vault is unlocked, until you revoke it in **Connections**.

If Connect is not available (for example an older desktop, browser policy that
blocks Native Messaging, or a vault that cannot hold device authorization),
expand **Other ways to connect** in the popup. In Vault Unified, open
**Connections → Browser extension**, generate a one-time pairing code, then copy
the local address and code into the extension before the countdown reaches zero.

The extension's ID is fixed by its manifest key, so every extracted copy has the
same ID. A browser paired with an earlier copy (whose ID came from its folder)
must connect once more; Connections labels the old record **Previous extension
ID** so you can revoke it.

Vault Unified fills only after you open the extension and choose an account.
If a page has multiple login forms, several password fields, a change-password
form, an iframe, or Shadow DOM fields, this version may refuse to fill and will
say why. It never treats an unsupported page as a successful fill.

The pairing token is kept only in `chrome.storage.session`. Locking or exiting
the desktop app, cancelling or regenerating pairing, or reaching the expiry
time makes the old token unusable.

## Account saving and persistent authorization

Version <version> includes account saving and optional persistent authorization.
Use desktop version <version>; v1.3.0 does not provide these endpoints. For v3 vaults, name and authorize the browser when pairing. It can
obtain fresh access after you unlock, including after either app restarts. A
non-exportable signing identity is stored in the extension's IndexedDB; access
tokens stay session-only. Revoke authorized browsers in desktop Connections.
Uncheck authorization for temporary pairing instead.

The installed desktop registers Native Messaging for this extension's fixed ID
when it starts, so the extension can find its current address, also before the
first connection. This channel returns public connection information plus a
per-run connect nonce that only lets this extension *ask* for your approval.
Browser policy may disable it; manual pairing remains available.

Choose **Read login from this page** or **Add manually**, review the account and
website, then confirm saving. Updates retain the previous password in history and
preserve other fields. No external service is updated automatically.

For registration/change-password tasks, first open the separate extension window.
It keeps a draft in memory while you finish the website action. Generate and fill
explicitly marked new-password fields, then confirm the website accepted the
password before saving. Closing the window, locking, or leaving the original
website clears the draft. No background form monitoring is used.

## Optional input-field suggestions

In the extension, expand **Choose accounts inside fields** and enable the current
website. To authorize an embedded website, enter its address separately. You can
also explicitly allow all HTTP/HTTPS websites, or disable all suggestions and
revoke those optional permissions. Ordinary popup filling still works with
suggestions off.

Click **V** next to a login field, select an account, or use **Alt+Shift+V** and
the arrow/Enter keys. Suggestions support separate username/password steps,
dynamic forms and accessible open Shadow DOM inputs. They fill the chosen form
without submitting it. One-time-code fields offer accounts with TOTP enabled.
An embedded form from another origin always requires confirmation in a separate
extension window showing the outer page and the actual destination.

Suggestions are off by default and record only site preferences locally.
Passwords and access tokens never go into persistent extension settings. A
changed document, replaced target, lock, expired confirmation or revoked site
permission prevents the pending fill. On unsupported fields, use the extension
popup or copy from the desktop. Configure the shortcut in the browser's extension
shortcut settings if another extension already uses it.

## Passkeys and extension updates

Enable passkeys for the chosen website in the extension. Create/sign-in requests
open a desktop confirmation; private keys stay in the encrypted vault. Cancel or
lock to stop. Use the website's other provider option when needed.

To update, replace files in the existing extracted folder and click Reload in
the extension manager. Keeping the directory retains the extension identity.
Remove duplicate old extensions. Desktop updates do not replace unpacked files.
Use the matching <version> desktop and extension from the same kit.
