# Vault Unified v1.1.5

Vault Unified v1.1.5 is a corrective Windows desktop release for gopass 1.16.x
integration. It retains the v1.1.4 KeePassXC compatibility corrections and v1.1.3
Bitwarden sync-state corrections.

## gopass runtime compatibility

- The configured gopass Store path now maps to gopass' documented runtime
  `mounts.path` configuration override. This makes the configured store effective
  for normal reads, writes, deletes, and availability checks without replacing
  existing gopass configuration overrides.
- gopass external IDs remain normalized, stable paths. Entries written by Vault
  Unified now store the original display title in a `title:` metadata line after
  the password, so a create/read-back cycle preserves the title and avoids a
  false synchronization conflict.
- Existing gopass values without that metadata remain compatible: their title
  continues to fall back to the final path component.

## Validation

- gopass 1.16.1 and Gpg4win 5.1.0 were downloaded from their official release
  channels and verified before use.
- A real isolated GPG- and Git-backed gopass store completed local
  create/push/read-back, direct external edit/pull/read-back, local
  edit/push/read-back, delete/remote-absence confirmation, restart, and final
  clean sync.
- The Python regression suite passes 238 tests, including gopass runtime Store
  path configuration and original-title round-trip coverage.

## Compatibility and upgrade notes

- Installing v1.1.5 does not rewrite existing v1/v2/v3 Vault Unified vault files
  or existing gopass entries.
- No data migration is required. Users can install v1.1.5 before configuring or
  continuing to use a gopass source.
