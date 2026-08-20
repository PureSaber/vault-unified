# Encrypted multi-source sync ledger

The sync ledger implements stage 5f without contacting an external service during migration or
tests. It is serialized inside each encrypted `SecretEntry` and keeps the legacy entry fields
alongside it so older readers can still recover title, username, password, notes, tags, IDs, and
source links.

## Per-entry and per-replica state

Each entry has a random content revision and one independent replica record per source. A replica
stores only encrypted metadata and its encrypted base snapshot:

- external ID and the adapter capability declaration used for the decision;
- trustworthy remote revision/token when available;
- canonical SHA-256 content fingerprint and full encrypted base snapshot;
- last acknowledged local content revision;
- durable operation ID, kind, state, creation time, and external ID while an operation is pending;
- last acknowledged operation ID, deletion acknowledgement, and absence state.

Fingerprints cover title, username, password, URL, notes, and ordered tags. They and every base or
conflict snapshot remain inside the encrypted vault. Operation IDs, error summaries, preferences,
the legacy migration marker, and CLI output contain no entry content.

Pull performs a per-source three-way comparison of local content, the last accepted base, and the
remote content. Only-local and only-remote changes advance without user choice. Identical
concurrent results converge. Differing concurrent results create an encrypted conflict record
containing base/local/remote snapshots. The configured primary source is only the displayed
recommendation; it never auto-selects password, notes, deletion, or link changes. When a source
lacks trustworthy revisions, the same comparison uses canonical fingerprints and remains
conservative.

## Adapter capabilities and absence

Capabilities are code declarations, not runtime guesses:

| Adapter | authoritative list | revision token | idempotent create | delete confirmation | absence means delete |
| --- | --- | --- | --- | --- | --- |
| Bitwarden | yes | yes | no | yes | no |
| Proton Pass | yes | yes | no | no | no |
| KeePassXC | yes | no | no | yes | no |
| gopass | yes | no | no | yes | no |

Consequently, no production adapter currently turns a missing list item into deletion. A missing
item is recorded as `unknown`. An adapter must separately declare both a complete authoritative
listing and reviewed absence-as-delete semantics before absence may create a deletion observation.
Partial, failed, disabled, or unavailable sources cannot purge local data.

## Durable remote-write saga

Create, update, and delete follow this sequence:

1. atomically persist operation intent and a random operation ID in the encrypted vault;
2. call the adapter, passing the operation ID where the adapter can use it;
3. read the remote entry back or confirm deletion;
4. compare the read-back fingerprint and persist acknowledgement.

If the process stops after a remote create but before acknowledgement, the next run reconciles
before retry. A non-idempotent create with no recoverable external ID remains `unknown` and is not
blindly repeated. An idempotent fake adapter proves that a retry reuses the same operation ID. If
the external ID was persisted before a read-back failure, the next run reads and acknowledges the
existing object without a second create. Adapter exceptions are reduced to action, source, and
exception type; their messages are not copied into vault status or API results because they may
contain secrets.

## Deletion and retention

A local delete atomically creates a tombstone before any adapter call. The tombstone contains a
random deletion revision, creation time, 30-day retention deadline, every linked replica that must
acknowledge, acknowledgements, and explicit abandonments. Successful remote deletion only records
an acknowledgement; it never purges the local entry.

Disabled, unavailable, partially failed, or unconfirmed replicas remain pending. The user may
explicitly abandon a replica only with `--confirm-abandon`, accepting that the remote credential
may remain. Local purge is a separate atomic command requiring `--confirm-purge`; it refuses until
all required replicas are acknowledged or abandoned and the retention deadline has elapsed.

```powershell
.\vault.cmd tombstones list --vault-path C:\isolated\vault.vault
.\vault.cmd tombstones abandon ENTRY_ID --source keepassxc --confirm-abandon --vault-path C:\isolated\vault.vault
.\vault.cmd tombstones purge ENTRY_ID --confirm-purge --vault-path C:\isolated\vault.vault
```

## Legacy conflict sidecar and rollback

New conflicts are embedded in the main encrypted vault and do not create `conflicts.vault`. On a
password-authenticated open, an existing legacy sidecar is authenticated and imported into entry
ledgers before a small adjacent marker is written. The marker contains only schema version, vault
filename, sidecar SHA-256, and `embedded` state. The original encrypted sidecar is never deleted or
modified. A marker failure can be retried; conflict IDs make re-import idempotent. A malformed or
unauthenticated sidecar fails closed instead of being silently ignored.

This is a metadata-compatible extension, not a vault-format migration. Older software can read the
legacy entry fields but does not understand the ledger and may drop it when saving. Before a code
downgrade, stop sync and retain/restore the atomic pre-5f backup. Rebuilding causality from live
remotes is intentionally not automatic. No release, tag, default-format change, telemetry, real
credential access, or external cleanup is part of 5f.

## Test contract

Tests use generated fake entries, isolated vaults, and in-memory fake adapters. They cover legacy
entry decoding, strict ledger tamper rejection, remote-only/local-only/concurrent comparisons,
missing revisions, independent multi-source acknowledgements, partial listing, documented remote
deletion, deletion conflicts, disabled replicas, retention and explicit abandonment, durable
intent ordering, non-idempotent duplicate prevention, idempotent retry, read-back recovery,
encrypted conflict persistence, legacy sidecar preservation, and secret-free public/error output.
