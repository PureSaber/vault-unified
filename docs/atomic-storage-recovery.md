# Atomic storage and crash recovery

Vault Unified never edits a managed local file in place. Legacy `secrets.vault`, encrypted
`conflicts.vault`, and plaintext `sync_prefs.json` writes use the same transaction protocol;
this does **not** change the legacy vault format or KDF.

## Write protocol

1. Acquire a per-target exclusive lock. Replacement callers may require the locked live
   SHA-256 to match the bytes used to build their candidate, and create-only callers may
   require the destination to remain absent; either mismatch fails instead of overwriting a
   concurrent writer.
2. Write a random, owner-only temporary file in the target directory, flush, and fsync it.
3. Read it back and run the format-specific validator.
4. Write and fsync a secret-free transaction journal containing names and SHA-256 digests.
5. Replace the target, preserving the old bytes under a unique backup name. Windows uses
   `ReplaceFileW`; POSIX uses a synced backup followed by same-filesystem `os.replace`.
6. Sync and revalidate the live file, then remove the completed journal.

Backups are named `<file>.bak.<transaction-id>`. They are intentionally never pruned
automatically in 5a, because deletion could remove the only copy a user intended to retain.
This means frequent writes can consume disk space until an explicit, separately reviewed
retention policy exists. Backups contain the same protection as their source: vault/conflict
backups are encrypted, while preference backups remain plaintext metadata.

## Recovery is inspect-first

An unfinished journal makes normal reads and writes fail closed with `Storage recovery
required`. Opening a vault never applies recovery automatically and never converts v1/v2 to
another format.

```powershell
# Read-only inspection (default)
.\vault.cmd storage inspect --vault-path C:\path\to\secrets.vault

# Still a dry-run unless --apply is present
.\vault.cmd storage recover --vault-path C:\path\to\secrets.vault
.\vault.cmd storage recover --vault-path C:\path\to\secrets.vault `
  --transaction-id <id> --apply
```

Recovery validates transaction IDs, bounded journal structure, digests, encryption, and
payload parsing. It can finalize an already committed replacement, discard an uncommitted
candidate while retaining the old live file, restore a synced new candidate, or restore the
last backup. An unexpected live file is first preserved as
`<file>.pre-recovery.<transaction-id>`. When the format validator proves that a live file is
valid but its digest is neither the recorded old nor new digest, it is a concurrent version
and always stops for manual recovery; it is never silently replaced by a temp or backup.
Other ambiguous/corrupt evidence also stops.

Locks are never silently broken. A lock at least ten minutes old can be inspected and then
explicitly quarantined; it is renamed rather than deleted:

```powershell
.\vault.cmd storage quarantine-stale-lock --vault-path C:\path\to\secrets.vault
.\vault.cmd storage quarantine-stale-lock --vault-path C:\path\to\secrets.vault --apply
```

The age threshold is a safety delay, not proof that a process is dead. Users must verify no
other Vault Unified process is writing before applying quarantine.
