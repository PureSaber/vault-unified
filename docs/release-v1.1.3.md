# Vault Unified v1.1.3

Vault Unified v1.1.3 is a corrective Windows desktop release for three Bitwarden sync-state
defects found during a real-account create, update, read-back, and delete test. It retains the
v1.1.2 release-integrity, clipboard, backup-cleanup, and shared-configuration fixes.

## Bitwarden round-trip correctness

- Vault Unified tags are now explicitly local-only metadata. They are excluded from external
  read-back comparison because none of the current adapters has a lossless native tag mapping.
- A tagged local entry can therefore be created or updated in Bitwarden without a false
  conflict, and later remote updates retain the local tags.
- Passwords, usernames, URLs, notes, and titles remain part of the authenticated remote
  comparison and continue to fail closed on a genuine mismatch.

## Conflict operation reconciliation

- Choosing the remote side of a conflict now acknowledges and clears the matching durable
  pending operation.
- The accepted remote snapshot and local replica revision are recorded together, preventing a
  resolved conflict from remaining spuriously dirty or requiring a second push.

## Bitwarden trash deletion confirmation

- Bitwarden items carrying `deletedDate` are treated as deleted by item lookup and listing.
- A normal Bitwarden soft delete can now be confirmed even though the CLI can still retrieve
  the item from Trash by ID.
- Retained tombstones remain encrypted for the configured 30-day safety period, but a tombstone
  whose required replicas all acknowledged deletion no longer counts as pending dirty work.

## Validation

- A real Bitwarden account completed pull, create, remote read-back, update, second read-back,
  soft delete, deletion reconciliation, and final pull using a generated disposable record.
- The final active baseline returned to 10 remote entries and 10 local entries with zero dirty
  entries and zero conflicts. The disposable record remains recoverable in Bitwarden Trash;
  this release never performs automatic permanent deletion.
- The Python regression suite passes 233 tests, including new coverage for tag preservation,
  pending-operation acknowledgement, trash detection, and acknowledged tombstone accounting.

## Compatibility and upgrade notes

- Installing v1.1.3 does not rewrite existing v1/v2/v3 vault files.
- Existing sync ledgers remain compatible; stored full-content fingerprints are unchanged.
- Users of v1.1.0 through v1.1.2 should install v1.1.3 and retain a verified encrypted backup
  until the post-install smoke check succeeds.
