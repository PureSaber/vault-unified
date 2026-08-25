# Vault Unified v1.1.2

Vault Unified v1.1.2 is an immutable reissue of the v1.1.1 corrective desktop release. It keeps
the same vault-safety fixes and adds a corrected post-publication provenance gate.

## Release provenance correction

- The release verifier now follows annotated Git tag objects until they resolve to a commit.
- The resolved commit must match the source commit recorded in the downloaded release manifest.
- The verifier still independently downloads every public asset and checks its exact byte size
  and SHA-256 digest after publication.
- The v1.1.1 assets passed build, install, launch, uninstall, size, and hash checks; its workflow
  ended red only because the old verifier compared the annotated tag object's SHA directly with
  the commit SHA. To preserve release immutability, v1.1.2 does not move or replace v1.1.1.

## Stable desktop and CLI configuration

- An explicit `VAULT_DATA_DIR` always places integration configuration and backup catalogs under
  that data root, including when the CLI is launched from a source checkout.
- Desktop and CLI status checks therefore use the same Bitwarden and other integration settings.

## Clipboard preservation

- Delayed clipboard cleanup is bound to the exact copied value.
- On Windows, comparison and clearing occur while holding the clipboard, so later user-copied
  content is preserved.

## Preview-confirmed backup cleanup

- Backup cleanup previews issue random, session-bound, single-use tokens that expire after five
  minutes.
- Apply requires the same retention policy and deletes only the exact previewed paths and
  SHA-256 values.
- Backups created after preview are excluded. Changed, pinned, missing, or unverifiable candidates
  are skipped with an error.

## Compatibility and upgrade notes

- Existing v1/v2/v3 vault files are not rewritten by installing v1.1.2.
- Existing legacy vaults remain readable and writable; migration to v3 remains explicit.
- Users of v1.1.0 or v1.1.1 should install v1.1.2 and retain a verified encrypted backup until
  the post-install smoke check succeeds.
