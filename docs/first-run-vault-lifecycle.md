# Explicit first-run vault lifecycle

The desktop application distinguishes opening an existing vault from creating or restoring
one. Entering a password on the unlock screen can no longer create a missing vault as a side
effect.

## Open an existing vault

When the configured vault path exists, the first screen reports its path and detected format
(`legacy` or `v3`) and offers password or enabled-device unlock. Existing legacy vaults remain
readable and writable; opening them does not migrate their bytes.

## Create a new vault

When no active vault exists, creation requires the master password twice. The API verifies the
confirmation and creates Vault Format v3 directly with Argon2id and AES-256-GCM. Creation uses
the existing atomic create-only writer and refuses any target that already exists.

The desktop API does not expose the legacy automatic-creation path. CLI compatibility remains
unchanged for users who deliberately invoke the existing setup commands.

## Restore an encrypted backup

Restore accepts a path to an encrypted Vault Unified backup and a password. It:

1. refuses to run when the active target already exists;
2. reads the source once and authenticates/decrypts the complete payload in memory;
3. atomically writes those exact encrypted bytes to the active target with a second validator;
4. opens the restored target before returning an authenticated session.

A wrong password, malformed backup, missing source, active target, or pending storage-recovery
journal leaves the target absent or unchanged. Restore never migrates the backup format and
never silently replaces the user's active vault.
