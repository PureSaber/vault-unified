# Vault Unified browser extension

The source branch adds reviewed account saving, persistent device authorization and optional Passkeys. These
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

Access tokens use `chrome.storage.session` only and expire after at most 12 hours.
Lock invalidates access. For v3 vaults, optional authorization stores a
non-exportable signing key in the extension's IndexedDB and its public identity
in Windows Credential Manager. Unlock the same vault and reconnect after app or
browser restarts without entering another code. Desktop Connections lists and
revokes devices. Forget pairing also revokes the identity while locked.

After the first authorized pairing, Native Messaging discovers the desktop's
current loopback address without receiving any authentication material. This
requires the matching desktop executable; a Python-only API retains manual
address entry. Legacy vaults and unchecked authorization use session pairing.
The extension does not launch or unlock the desktop. A Passkey confirmation can
bring the running desktop window forward.

The extension receives login titles and usernames for the displayed site's host,
scheme and port. Other subdomains do not match unless explicitly allowed by the
account's extra-website or base-domain rules.
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

## Passkeys / 通行密钥

Enable the website under **Choose accounts inside fields**, then check **Use
Vault Unified Passkeys on authorized websites**. Creation and sign-in require
checking the website/account and entering the master password in the desktop
window. The extension receives public authentication responses, never private
keys or the master password. You can cancel or use another provider; unsupported
requests continue to the browser. See [the workflow and tested scope](../../docs/passkeys.md).

在「输入框内选择账号」中开启网站后，勾选「在已授权网站使用 Vault Unified
通行密钥」。创建或登录时，在桌面窗口核对网站和账号，并用主密码确认。
可以取消或选择其他提供方。通行密钥默认关闭，并随加密备份和多电脑同步保存。

## Developer validation

After installing the project's Python API environment and desktop Playwright
dependencies, run `node apps/desktop/tests/live/browser-daily-use.mjs` from the
repository. This launches the actual unpacked extension and API against an
isolated generated vault and local fake website, covers save/fill/change/history/
lock/resume/revocation, then removes its temporary profile and vault. It never uses
the user's browser profile or passwords. It supplements the Python and popup
regressions; it is not an installed-desktop or independent usability acceptance.
