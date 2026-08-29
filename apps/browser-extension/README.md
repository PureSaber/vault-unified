# Vault Unified Personal Fill extension

This unpacked Manifest V3 extension fills a matching login only after the user
opens its popup and chooses the entry. It never stores the desktop bootstrap
secret, master password, or copied vault data.

## Install and pair

1. In Chrome or Edge, open the extensions page, enable **Developer mode**, and
   choose **Load unpacked**.
2. Select this `apps/browser-extension` directory.
3. With the desktop vault unlocked, open **Settings → Chromium browser fill**
   and create a pairing code.
4. Open the extension popup, paste the shown local address and pairing code,
   then pair within five minutes.

The connection is memory-only: it is invalidated when the desktop vault locks,
when the desktop app exits, after 12 hours, or if a new pairing code is made.
The extension receives login titles and usernames for the active site's exact
host; a password is supplied only after clicking a specific entry in the
extension popup.
