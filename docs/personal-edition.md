# Personal edition workflow

Vault Unified v1.4 is a local-first Windows password manager. Start with the
[installation and migration guide](personal-edition-start.md). A cloud account or
an existing password manager is not required.

## Everyday setup

1. Create a vault, then configure an encrypted backup in **Security & recovery**.
   Keep a separate emergency recovery kit and its recovery code in different
   locations. Scheduled backups run while the application is open and unlocked.
2. Import Chrome or Edge CSV passwords with preview, or add accounts directly.
   Delete the plaintext CSV after checking the imported entries.
3. Load the matching extension and pair it in **Connections**. Persistent browser
   authorization is optional; it reconnects only after the desktop vault unlocks.
4. Enable website suggestions and Passkeys for the websites you choose. Filling
   never submits the login form. Cross-origin frames need separate permission.

## Accounts and recovery

Favorites, tags, type filters and sorting organize accounts. Archive keeps items
indefinitely; trash keeps them for 30 days. Neither appears in normal browser fill
candidates. Bulk changes, duplicate merging and recovery use review and confirmation.
History lets you choose individual fields to restore into the current edit draft.

Login, secure-note, card, identity, SSH-key, recovery-code, software-license and API
credential templates support custom fields, TOTP and small attachments. Generate
passwords or passphrases locally; encrypted generation history keeps up to 100
values for at most 30 days. See [credential templates](credential-templates.md),
[TOTP](totp-verification-codes.md) and [password recovery](generated-password-recovery.md).

## Data compatibility and transfers

The encrypted Vault Format v3 container remains in use. Personal-edition features
require payload schema 3, including encrypted vault-wide metadata. Existing vaults
offer an explicit upgrade that retains a pinned encrypted old-format backup before
writing. Older clients refuse the new payload instead of dropping unknown data.
See [payload migration](personal-payload-upgrade.md).

Plaintext JSON transfers include supported personal entry fields and attachments;
CSV omits attachments. Plaintext transfers are not complete vault backups and do
not export Passkey private keys. Use encrypted backups or the new-computer migration
package for complete recovery, including histories, TOTP, Passkeys and vault metadata.
An isolated recovery rehearsal checks the package without replacing the active vault.

## Optional networking

[Personal computer sync](personal-computer-sync.md) uses a chosen folder or WebDAV
server for the complete encrypted vault. Non-overlapping changes merge; concurrent
changes and delete conflicts require a choice. Hello keys and browser device
authorization stay on each computer.

External password-manager connectors remain separate and transfer only their
documented fields; see [connector field support](sync-field-support.md).
[Encrypted sharing](encrypted-sharing.md) provides expiring links and independent
household vaults through an optional separately deployed service. Personal entries
are not added to a shared vault automatically.

Exposure queries and automatic update checks are off by default. Updates verify
the signed version and installer, then retain an encrypted backup before installation.
See [signed updates](signed-updates.md).

## Windows and browser use

Global quick search, tray operation, Windows Hello and user-triggered application
auto-type supplement the main window. Every launch first requires the master
password; Hello can unlock later in that session. Lock/suspend clears vault access.
Auto-type binds to the selected window and stops if focus changes.

The Chrome/Edge extension supports saved-account selection, stepwise forms, TOTP,
multiple website rules and Passkeys. Persistent authorization uses an extension-local
non-exportable signing key; access tokens stay in session storage. Revoke a browser
in Connections to remove its access. See [browser setup](browser-extension-install.md)
and [Passkeys](passkeys.md).

Mobile applications and external-manager Passkey conversion are outside this version.
The desktop API listens only on this computer. Final device-specific checks are in
the [installed acceptance checklist](personal-edition-acceptance.md).
