# Vault Unified v1.1.1

Vault Unified v1.1.1 is a corrective Windows desktop release. It preserves existing encrypted
vault compatibility and supersedes v1.1.0 without replacing or retagging the earlier release.

## Corrected packaged sidecar

- The release build now fails immediately when editable dependency installation fails.
- PyInstaller receives the repository source path explicitly, preventing a packaged sidecar
  that starts without the `vault_unified` module or without current API routes.

## Stable desktop and CLI configuration

- An explicit `VAULT_DATA_DIR` now always places integration configuration and backup catalogs
  under that data root, even when the CLI is launched from a source checkout.
- Desktop and CLI status checks therefore see the same Bitwarden and other integration settings.

## Clipboard preservation

- The delayed clipboard cleanup is bound to the exact copied value.
- On Windows, comparison and clearing occur while holding the clipboard, so content copied by
  the user after a password is never cleared by the old timer.

## Preview-confirmed backup cleanup

- Backup cleanup previews now issue random, session-bound, single-use tokens that expire after
  five minutes.
- Apply requires the same retention policy and deletes only the exact paths and SHA-256 values
  shown in that preview.
- Backups created after preview are excluded. Candidates that changed, were pinned, disappeared,
  or became unverifiable are skipped with an error.

## Compatibility and upgrade notes

- Existing v1/v2/v3 vault files are not rewritten by installing v1.1.1.
- Existing legacy vaults remain readable and writable; migration to v3 remains explicit.
- Users of v1.1.0 should install v1.1.1 over the previous version and retain a verified encrypted
  backup until the post-install smoke check succeeds.
