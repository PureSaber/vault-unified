# Install the browser extension

The browser extension is an optional release download for Chrome and Edge on
the same Windows computer as Vault Unified.

1. Open the latest Vault Unified release and download
   `Vault-Unified-Browser-Extension-v<version>.zip` beside the EXE or MSI.
2. Extract the ZIP. In `chrome://extensions` or `edge://extensions`, enable
   **Developer mode**, choose **Load unpacked**, and select the extracted
   directory containing `manifest.json`.
3. Unlock Vault Unified and open **Connections → Browser extension**.
4. Copy the local address and one-time pairing code into the extension popup
   before the five-minute countdown ends.

The token is session-only. Locking or exiting Vault Unified, cancelling or
regenerating pairing, or waiting for expiry invalidates it. The extension does
not silently fill ambiguous multi-form, change-password, iframe, or Shadow DOM
pages.
