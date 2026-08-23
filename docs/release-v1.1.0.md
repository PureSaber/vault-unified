# Vault Unified v1.1.0

Vault Unified v1.1.0 is a security and usability release for the Windows desktop password
vault. It keeps existing encrypted vaults compatible and never migrates a vault automatically.

## Safer secret editing and error handling

- Empty passwords and notes are now preserved as explicit updates.
- Literal mask-like values such as `****` or leading bullet characters are no longer confused
  with desktop placeholders.
- List/search responses expose presence flags instead of fake secret values.
- Failed external CLI commands and timeout messages are sanitized before reaching logs or API
  responses.

## Source-field fidelity

- Bitwarden secondary URIs, match rules, TOTP, custom fields, folders, favorite/reprompt state,
  secure-note type, organization/collection metadata, and attachment presence are retained in
  encrypted source metadata.
- Updates begin from the complete remote item and refuse a write when unsupported ownership or
  attachment state cannot be reconstructed safely.
- Secure Notes are modeled as notes rather than passwords.

## V3-first desktop lifecycle

- The desktop now distinguishes opening, creating, and restoring a vault.
- New desktop vaults require password confirmation and are created directly as Vault Format v3
  using Argon2id and AES-256-GCM envelope encryption.
- Existing legacy vaults remain readable and writable; migration remains explicit and dry-run
  first.
- Restore validates the complete encrypted backup before an atomic, non-overwriting activation.

## Protected integration credentials

- Bitwarden, KeePassXC, and Proton Pass secrets are stored in the operating-system credential
  store instead of desktop-generated plaintext `.env` files.
- Non-secret paths and server names use validated LocalAppData configuration.
- The desktop can save, test, and clear each integration without returning stored secret values.

## Backup and recovery center

- The desktop inventories encrypted automatic and manual backups with hash, size, format,
  verification, and pin state.
- Manual backups can be copied to a separate directory without decrypting them.
- Cleanup is preview-first and can select only verified, unpinned local atomic backups under a
  newest/daily/weekly retention policy.
- Restore retains the displaced active vault, reopens the committed bytes, and invalidates the
  old session.

## Preview-confirmed synchronization

- New installations start local-only with automatic pull and push disabled.
- Desktop synchronization first builds a read-only per-source plan showing additions, updates,
  conflicts, observed deletions, creates, updates, deletes, unavailable sources, and unknown
  outcomes.
- Confirmation tokens are single-use, expire after five minutes, belong to one unlocked
  session, and bind both local and remote state.
- Any local setting change, local entry change, remote change, expiry, session change, or replay
  blocks execution and requires a fresh preview.

## Compatibility and upgrade notes

- Existing v1/v2/v3 vault files are not rewritten merely by installing v1.1.0.
- New desktop-created vaults use v3; older builds cannot open those v3 files.
- Existing explicit `enabled_sources: null` settings retain their historical “all sources”
  meaning. Missing synchronization settings now use conservative local-only defaults.
- Integration secrets previously stored in `.env` are still accepted as a development fallback,
  but the desktop does not copy them automatically into the OS credential store.
- Keep the v1.0.5 installer and a verified encrypted backup until v1.1.0 has completed the
  post-release smoke checks on the target Windows account.
