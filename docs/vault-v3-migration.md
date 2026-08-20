# Explicit Vault Format v3 migration and rollback

Legacy-to-v3 migration is opt-in, dry-run first, and local-only. Nothing runs at startup,
unlock, edit, sync, install, or upgrade time. The default `vault init` path remains legacy;
only `vault init-v3` or the explicit migration command can create a v3 live file.

This workflow never reads or writes the existing global raw-master-password keyring record.
Use generated test data when validating it. Do not experiment on the only copy of a real
vault.

## Dry-run and apply

Dry-run authenticates and decodes the legacy file, validates payload version 1/2, computes
the version-2 normalization and entry count, checks the conservative free-space requirement,
and reports the legacy SHA-256. It does not derive the new Argon2id key, generate randomness,
create a receipt, or change any file or timestamp.

```powershell
# Read-only default
.\vault.cmd migrate-v3 --vault-path C:\isolated\fake.vault

# Explicit activation; hidden prompts ask for legacy and new V3 passwords
.\vault.cmd migrate-v3 --vault-path C:\isolated\fake.vault --apply
```

For non-interactive isolation, `VAULT_PASSWORD` supplies only the legacy password and
`VAULT_NEW_PASSWORD` supplies only the new v3 password. A missing new-password value never
falls back to `VAULT_PASSWORD`.

Apply refuses a v3/unknown framed source, an existing unfinished migration receipt, a
symbolic-link/non-file source, unresolved atomic-storage journal, invalid entry, wrong
password, changed live digest, or insufficient space. It creates and validates evidence in
this order:

```text
planned receipt
  -> exact non-overwriting legacy backup
  -> authenticated payload-equivalent V3 candidate
  -> compare-and-swap atomic activation
  -> activated receipt
```

The space reserve is the greater of 1 MiB or a conservative estimate covering three copies
of the source, normalized payload, and maximum-size receipts. The actual atomic writer may
require more filesystem overhead; disk-full errors still fail closed.

## Durable artifacts

For migration ID `<uuid>`, all evidence is adjacent to the selected vault:

```text
<vault>.migration-v3.<uuid>.legacy     exact legacy bytes
<vault>.migration-v3.<uuid>.candidate  authenticated V3 candidate
<vault>.migration-v3.<uuid>.json       secret-free recovery receipt
<vault>.bak.<transaction-id>           atomic pre-activation backup
```

The `.legacy` and `.candidate` artifacts are logically immutable: creation is exclusive,
they are never overwritten or pruned by migration code, and every later use rechecks their
digest and authentication. Filesystem/administrator tampering remains possible and is
detected before activation or rollback.

The closed-schema receipt records only artifact basenames, formats, migration/vault IDs,
state, entry count, timestamps, SHA-256 values, and atomic transaction/backup names. It does
not contain a password, key, plaintext payload hash, entry title, or entry secret. Artifact
names must exactly derive from the target basename and canonical migration UUID, so a
tampered receipt cannot redirect rollback outside the directory.

Do not delete migration artifacts or generic backups automatically. Retirement is a separate
destructive decision and reliable SSD secure deletion is not claimed.

## Inspect and resume after interruption

Every phase is idempotently recoverable from durable evidence. Inspection authenticates the
legacy backup and v3 candidate with both supplied passwords, checks payload equivalence,
receipt state, digests, vault ID, and live bytes, then reports one next action without writing:

```powershell
.\vault.cmd migration inspect --receipt C:\isolated\fake.vault.migration-v3.<uuid>.json
.\vault.cmd migration resume  --receipt C:\isolated\fake.vault.migration-v3.<uuid>.json

# Only after inspecting the reported action
.\vault.cmd migration resume  --receipt C:\isolated\fake.vault.migration-v3.<uuid>.json --apply
```

Resume can create a missing backup, build a missing candidate, activate a recorded candidate,
or finalize a receipt when activation completed before a crash. If receipt state claims an
artifact that is missing, the artifact is corrupted/tampered, or live bytes match neither
the recorded legacy nor candidate digest, it stops for manual recovery. It never guesses by
modification time.

The receipt itself also uses the atomic writer. If a crash interrupts a receipt update, its
closed schema has a dedicated inspect-first recovery command that needs no password and never
interprets the receipt as an encrypted vault:

```powershell
.\vault.cmd migration list --vault-path C:\isolated\fake.vault
.\vault.cmd migration receipt-recover --receipt C:\isolated\fake.vault.migration-v3.<uuid>.json
.\vault.cmd migration receipt-recover `
  --receipt C:\isolated\fake.vault.migration-v3.<uuid>.json --apply
```

`migration list` recognizes only canonical receipt names and receipt-journal names. This lets
it report the intended receipt path even when the first receipt replacement did not reach the
live filename.

An unfinished generic atomic-write journal remains under the existing inspect-first storage
flow and must be resolved before migration resume:

```powershell
.\vault.cmd storage inspect --vault-path C:\isolated\fake.vault
.\vault.cmd storage recover --vault-path C:\isolated\fake.vault
```

## Rollback

Rollback is also dry-run first. It requires the activated receipt, exact immutable legacy
backup, exact candidate, current live file, legacy password, and v3 password:

```powershell
.\vault.cmd rollback-v3 --receipt C:\isolated\fake.vault.migration-v3.<uuid>.json
.\vault.cmd rollback-v3 --receipt C:\isolated\fake.vault.migration-v3.<uuid>.json --apply
```

Apply atomically restores the original legacy bytes byte-for-byte and preserves the current
v3 bytes as a unique generic backup before marking the receipt `rolled_back`. If replacement
commits but the receipt update is interrupted, rerunning rollback recognizes the exact legacy
digest and finalizes the receipt without a second replacement.

Rollback deliberately refuses if the live v3 digest differs from the original activated
candidate. That means the v3 vault was edited, rotated, or replaced after migration; silently
restoring the old legacy copy would lose those changes. Export/reconcile the newer data under
a separately reviewed recovery procedure instead.

The implementation does not make v3 readable by pre-v3 software, erase an old keyring record,
publish a release, remove migration evidence, or change default creation. Device-slot and
rollback-anchor work remains the independent 5e stage.
