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
