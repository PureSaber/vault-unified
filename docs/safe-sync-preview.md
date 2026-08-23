# Safe sync preview and conservative defaults

Vault Unified treats synchronization as a potentially destructive operation.

## New-vault defaults

When no synchronization preference file exists, the application starts with:

- no external source enabled;
- automatic push after edits disabled;
- automatic pull disabled;
- the local vault as the primary source.

An existing preference file keeps explicit values. In particular, an explicit
`"enabled_sources": null` continues to mean all remote sources for compatibility.
A missing field uses the new conservative default.

## Two-phase desktop synchronization

The desktop sidecar exposes:

1. `POST /api/sync/preview`
2. `POST /api/sync/execute`

Preview reads the selected remote sources and the encrypted local vault, then returns counts
for expected additions, updates, conflicts, deletions, pending operations, and unavailable
sources. Preview never calls a remote create, update, or delete method and verifies that the
local vault fingerprint did not change while the plan was built.

The response contains a random, single-use token. The token:

- is stored only in sidecar memory;
- belongs to exactly one unlocked session;
- expires after five minutes;
- binds the selected sources and pull/push direction;
- binds a canonical fingerprint of local entries and sync preferences;
- binds a digest of the exact remote state read during preview.

Before execution, the sidecar consumes the token, rechecks the local fingerprint, rebuilds
the read-only remote preview, and compares its digest. Any local preference change, local
entry change, remote change, session change, expiry, or replay causes a `409` response and no
sync execution.

Legacy direct sidecar write endpoints now return `409` and instruct callers to use the
preview/execute flow. The Python CLI still invokes the underlying sync engine directly for
advanced automation; users of that path are responsible for their own approval boundary.

## Failure behavior

Error text returned by preview contains exception class names only, not remote command
output or credential values. A failed or stale preview token is consumed and cannot be
retried. The user must create a fresh plan.
