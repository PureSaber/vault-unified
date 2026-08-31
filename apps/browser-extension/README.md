# Vault Unified Personal Fill extension

This unpacked Manifest V3 extension fills a matching login only after the user
opens its popup and chooses the entry. It never stores the desktop bootstrap
secret, master password, or copied vault data.

## Install and pair

1. Download the browser-extension ZIP from the same GitHub release as the
   desktop installer and extract it.
2. In Chrome or Edge, open the extensions page, enable **Developer mode**,
   choose **Load unpacked**, and select the extracted directory.
3. With the desktop vault unlocked, open **Connections → Browser extension**
   and create a pairing code.
4. Open the extension popup, paste the shown local address and pairing code,
   then pair within five minutes.

The connection is memory-only: it is invalidated when the desktop vault locks,
when the desktop app exits, after 12 hours, or if a new pairing code is made.
The extension receives login titles and usernames for the active site's exact
host; a password is supplied only after clicking a specific entry in the
extension popup.

Ambiguous multi-form, change-password, iframe, and Shadow DOM pages are
reported as unsupported instead of being described as successfully filled.
