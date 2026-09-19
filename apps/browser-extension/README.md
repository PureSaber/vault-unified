# Vault Unified browser extension

The source branch adds reviewed account saving and same-run reconnection. These
features are not in the published v1.3.0 installers; run the matching desktop/API
source when testing this branch.

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

Access tokens and optional reconnection credentials use `chrome.storage.session`
only. Lock invalidates access tokens. With a v3 vault and "Reconnect" enabled,
unlock the same vault and choose reconnect without entering a new code. The
connection expires after 12 hours, when either app restarts, or when pairing is
cancelled/regenerated. Legacy vaults require pairing again after lock. The desktop
can revoke remembered connections from Connections even after a lock/unlock.

The extension receives login titles and usernames for the displayed site's host,
scheme and port (a leading `www.` is normalized). Other subdomains do not match.
Passwords are read only on explicit actions. Status checks do not extend idle time.

## Daily use

- **Read login from this page** reads an unambiguous visible form only when clicked.
  **Add manually** supports passwords held in notes or memory.
- Select an existing account to update, or create a new account. Review the site,
  name and username, confirm the password works on the website, then save.
- For registration or password changes, first choose **Open a window for
  registration / password changes**. It stays open while you use the website.
  Generate a password, fill explicitly marked new-password fields, complete the
  website operation, then return to review and save. Website success is confirmed
  by you; the extension does not infer it from a submit click.
- Updates preserve other fields and encrypted history. Saves are local; they do
  not automatically push to connected providers. Duplicate usernames on a site
  require selecting the existing account. Cancellation writes nothing.
- Drafts exist only in the open window's memory and are cleared on close, detected
  lock/disconnection, or cross-origin navigation. Do not close the window before
  saving a generated password. A network failure during saving has an unknown
  outcome: reconnect and check the account before trying again.

Normal login filling refuses change-password pages. The separate new-password
action accepts one form with one or two `autocomplete="new-password"` fields and
leaves current-password fields untouched. Ambiguous multi-form, iframe and Shadow
DOM cases require manual entry. Chinese and English are available in the popup.

## Developer validation

After installing the project's Python API environment and desktop Playwright
dependencies, run `node apps/desktop/tests/live/browser-daily-use.mjs` from the
repository. This launches the actual unpacked extension and API against an
isolated generated vault and local fake website, covers save/fill/change/history/
lock/resume/revocation, then removes its temporary profile and vault. It never uses
the user's browser profile or passwords. It supplements the Python and popup
regressions; it is not an installed-desktop or independent usability acceptance.
