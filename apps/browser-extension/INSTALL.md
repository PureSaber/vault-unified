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
5. In Vault Unified, open **Connections → Browser extension**, generate a
   one-time pairing code, then copy the local address and code into the
   extension popup before the countdown reaches zero.

Vault Unified fills only after you open the extension and choose an account.
If a page has multiple login forms, several password fields, a change-password
form, an iframe, or Shadow DOM fields, this version may refuse to fill and will
say why. It never treats an unsupported page as a successful fill.

The pairing token is kept only in `chrome.storage.session`. Locking or exiting
the desktop app, cancelling or regenerating pairing, or reaching the expiry
time makes the old token unusable.

## Account saving in development builds

The development source includes account saving and optional same-run reconnection;
the published v1.3.0 desktop does not provide these endpoints. Use a matching
desktop build. For v3 vaults, a remembered connection can obtain fresh access after
you unlock. Restarting either app, cancelling pairing, or 12 hours requires pairing
again. No access or reconnection credential is stored persistently.

Choose **Read login from this page** or **Add manually**, review the account and
website, then confirm saving. Updates retain the previous password in history and
preserve other fields. No external service is updated automatically.

For registration/change-password tasks, first open the separate extension window.
It keeps a draft in memory while you finish the website action. Generate and fill
explicitly marked new-password fields, then confirm the website accepted the
password before saving. Closing the window, locking, or leaving the original
website clears the draft. No background form monitoring is used.
