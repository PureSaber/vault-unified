# Vault Unified v1.0.5

This release delivers the reviewed maintenance and Vault Format v3 implementation series
merged after v1.0.4. It does not automatically migrate an existing vault, change the default
legacy format, collect telemetry, or require real password-manager data.

## Security and storage

- Atomic same-directory writes, validation, backups, journals, and explicit crash recovery.
- Explicit opt-in Vault Format v3 with RFC 9106 Argon2id parameters and AES-256-GCM KEK/DEK
  envelope encryption.
- Explicit password and DEK rotation with recoverable prior bytes.
- Dry-run-first legacy-to-v3 migration, immutable legacy backup, resumable phases, and
  rollback that refuses to discard post-migration edits.
- Optional Windows Credential Manager device unlock using a random device KEK and an exact
  backend allowlist. Password recovery remains available.

## Synchronization

- Encrypted per-entry, per-replica synchronization ledger with three-way comparisons.
- Durable remote-operation intents and read-back acknowledgement to prevent blind duplicate
  retries after an unknown outcome.
- Embedded encrypted conflict snapshots and a password-authenticated, byte-preserving import
  path for the legacy conflict sidecar.
- Retained deletion tombstones with per-source acknowledgement, explicit abandon, and a
  minimum retention period before explicit purge.
- Production adapters do not infer deletion from a missing list result.

## Release engineering

- Automatic release workflow activation for reviewed `v*` tags while ordinary branch and PR
  runs continue to skip the release job.
- GitHub Actions upgraded to Node 24-capable, full-SHA-pinned revisions with read-only default
  token permissions; release write permission remains job-local.
- RustSec CI fails vulnerabilities and keeps all 17 registered upstream/target-scoped warnings
  visible with dated review conditions.

## Compatibility and rollback

- Existing legacy v1/v2 vaults remain the default and continue to be readable and writable.
- Creating or migrating to v3 is explicit. Builds before v1.0.5 cannot open a v3 vault.
- Do not open and save a v1.0.5 sync-ledger vault with an older build: restore the retained
  pre-v1.0.5 atomic backup before downgrading.
- Migration evidence and atomic backups are intentionally not pruned automatically.
- Device unlock is a same-Windows-user convenience boundary, not a second authentication
  factor. Python cannot guarantee complete in-memory zeroization of immutable objects.

See `docs/post-release-runbook.md`, `docs/vault-v3-migration.md`,
`docs/vault-v3-keyring.md`, and `docs/sync-ledger.md` before migration, downgrade, or rollback.
