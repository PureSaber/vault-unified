# Vault Unified v1.1.4

Vault Unified v1.1.4 is a corrective Windows desktop release for KeePassXC
2.7.x integration behavior validated against the official CLI and isolated KDBX
databases. It retains all v1.1.3 Bitwarden sync-state corrections.

## KeePassXC CLI compatibility

- Connection validation now supplies the configured database path to the official CLI.
- Entry reads use `show -s --all`; `-a` requires an attribute value in current KeePassXC
  releases and previously shifted positional arguments.
- Recursive entry listing uses flat paths. Configured groups are prefixed back onto leaf
  output so external IDs remain stable and unambiguous across groups.

## Recoverable deletion confirmation

- KeePassXC's native `rm` moves an entry to its recycle bin rather than permanently erasing it.
- The adapter identifies the recycle-bin group through the database XML's `RecycleBinUUID`,
  rather than a locale-specific name, and excludes its entries from active sync reads.
- A delete therefore acknowledges the Vault Unified tombstone while leaving the native
  KeePassXC recovery path available; trashed entries are not re-imported as new credentials.

## Validation

- KeePassXC 2.7.12 was downloaded from the official release and verified against its published
  SHA-256 digest before use.
- A real isolated KDBX test completed local create/push/read-back, external edit/pull/read-back,
  local edit/push/read-back, recoverable delete/tombstone acknowledgement, restart, and final
  clean sync.
- A grouped KDBX entry was listed and read with its complete `group/entry` external ID.
- The Python regression suite passes 236 tests, including explicit coverage for current CLI
  read syntax, database availability, full grouped paths, and language-independent recycle-bin
  filtering.

## Compatibility and upgrade notes

- Installing v1.1.4 does not rewrite existing v1/v2/v3 Vault Unified vault files.
- Existing KeePassXC databases are not converted. Deletes made through Vault Unified remain
  recoverable in KeePassXC's recycle bin, subject to the database's own retention and empty-bin
  actions.
- Users of v1.1.3 should install v1.1.4 before enabling a KeePassXC source.
