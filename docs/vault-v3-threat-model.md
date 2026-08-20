# Vault Format v3 design and threat model

Status: accepted design target, not an implemented or released format. This document is the
gate for the ordered 5a-5f implementation series. No implementation PR may weaken a `MUST`
without a new design review.

## 1. Scope and current compatibility boundary

The v1.0.4 local vault is a legacy, headerless byte string:

```text
16-byte scrypt salt || 12-byte AES-GCM nonce || ciphertext-and-tag
```

Its scrypt parameters (`N=16384, r=8, p=1`) exist only in code. The decrypted JSON contains
payload version 1 or 2. Loading version 1 normalizes entry fields in memory; a later ordinary
save writes payload version 2. The current writer directly replaces the file contents. The
separate `conflicts.vault` uses the same legacy encryption, while `sync_prefs.json` is
plaintext. The current keyring entry stores the master password itself.

Vault Format v3 changes the encrypted *container*, not merely the JSON payload version. It
MUST meet all of these compatibility rules:

- Existing v1/v2 vault bytes remain readable with the existing scrypt parameters. Detection
  is by the absence of the complete v3 magic, never by trying several KDFs after a v3 parse or
  authentication failure.
- Opening, inspecting, or dry-running a legacy vault MUST NOT write it. Normal legacy writes
  remain legacy v2 and use the 5a atomic writer; they MUST NOT silently migrate to v3.
- A v3-capable build MUST reject an unknown container version without writing. A v3 parse,
  bounds, unwrap, or authentication failure MUST NOT fall back to the legacy parser.
- A pre-v3 build cannot read v3. Migration therefore preserves an immutable, byte-for-byte
  legacy backup and a recovery receipt until the user explicitly confirms retirement.
- There is no automatic migration at startup, unlock, edit, sync, or release installation.
  New v3 vault creation is explicit until the migration UX has shipped and been reviewed.

## 2. Assets, actors, and security goals

Protected assets are entry secrets, encrypted conflict snapshots, DEKs/KEKs, master-password
material, source links, tombstones, and integrity-critical sync metadata. Security metadata
such as format/KDF identifiers may be visible but MUST be authenticated.

The design addresses:

- offline theft or copying of vault files and backups;
- maliciously modified, truncated, replayed, or resource-exhausting files;
- power loss, disk-full, interrupted replacement, and concurrent writers;
- a buggy, stale, or compromised remote adapter/source returning conflicting data;
- a same-user process reading files or invoking the local application boundary;
- migration interruption at every durable step.

The design does not claim protection after compromise of the unlocked process, the OS
kernel/administrator, a hardware keylogger, or an authorized remote password-manager
account. Python cannot guarantee complete zeroization of immutable objects; implementations
MUST minimize plaintext/key lifetime and avoid copies, but MUST document this residual risk.
Availability against an attacker who can delete every local file and backup is also out of
scope.

## 3. v3 container and authenticated parsing

### 3.1 Framing

The proposed on-disk framing is:

```text
8 bytes  magic = "VLTUV3\r\n"
4 bytes  unsigned big-endian header length
N bytes  UTF-8 JSON header
rest     payload AES-256-GCM ciphertext and 16-byte tag
```

The implementation MUST parse the fixed prefix and validate size limits before allocating,
decoding JSON, or running a KDF. The header uses a closed schema: duplicate JSON names,
unknown required algorithms, wrong types, non-canonical base64url, invalid UUIDs, missing
fields, trailing bytes, and integer overflow are errors. Unknown optional fields MUST be
namespaced and size-bounded. A parser never repairs a source file.

The header carries at least:

- `format_version=3`, `vault_id`, content `generation`, `key_generation`, and `payload_schema`;
- the payload cipher identifier, fresh 96-bit payload nonce, and exact plaintext/ciphertext
  lengths;
- a random `dek_id` and one or more typed DEK wrapping slots;
- for a password slot: slot ID, Argon2 version/parameters, salt, wrap cipher identifier,
  fresh 96-bit wrap nonce, and wrapped DEK with tag.

All encoded cryptographic fields have an exact length. `vault_id`, `dek_id`, and slot IDs are
random 128-bit identifiers. Every successful content write increments `generation` and uses
a fresh payload nonce. No nonce may repeat under the same key; the cryptography project
explicitly warns that AES-GCM nonce reuse compromises security and recommends a 96-bit nonce
([AES-GCM documentation](https://cryptography.io/en/stable/hazmat/primitives/aead/)).

### 3.2 Authenticated contexts

AAD is a deterministic, length-prefixed binary encoding of validated typed fields, not a
re-serialization of JSON.

- Each wrap slot authenticates the domain string `vault-unified:v3:wrap`, format and cipher
  IDs, `vault_id`, `dek_id`, `key_generation`, slot ID/type, and every KDF parameter including
  salt and the wrap nonce.
- The payload authenticates `vault-unified:v3:payload`, format and cipher IDs, `vault_id`,
  `dek_id`, `generation`, `payload_schema`, payload nonce, and declared plaintext/ciphertext
  lengths, plus a digest of canonical namespaced extensions.

Thus changing a KDF parameter, swapping a slot across vaults, changing a generation, or
splicing ciphertext fails authentication. Slot removal can still cause denial of service but
cannot disclose plaintext or create a usable attacker-controlled slot.

Whole-file replay of an older, valid v3 generation cannot be proven from that file alone. A
migration receipt detects accidental local downgrade; after 5e, an optional keyring anchor
stores the highest observed `(vault_id, generation, file digest)` and makes a lower generation
fail closed into recovery/read-only mode. If that external anchor is absent or deleted,
cryptographic rollback detection is not promised and the UI MUST say so.

## 4. Argon2id policy and legacy KDF handling

Password slots derive a 32-byte KEK using Argon2id version 19, a fresh 16-byte salt, and the
password's UTF-8 bytes. New slots use `m=65536 KiB`, `t=3`, and `p=4`. These are the second
recommended, memory-constrained parameters in
[RFC 9106](https://www.rfc-editor.org/rfc/rfc9106.html). Parameters are stored per slot so a
future policy upgrade does not change old-slot derivation.

Before a KDF call, the reader MUST enforce all of these limits:

| Input | Accepted v3 range |
|---|---|
| algorithm/version/output | Argon2id / 19 / exactly 32 bytes |
| salt | 16-32 bytes |
| memory | 65,536-262,144 KiB |
| passes | 1-6 |
| lanes | 1-4 and `memory >= 8 * lanes` |
| work product | `memory_kib * passes <= 786432` |
| password | at most 1,024 UTF-8 bytes |
| simultaneous KDFs | one per process by default |

The complete file is capped at 256 MiB, the header at 64 KiB, decoded JSON nesting at 32,
and entry count at 100,000. Implementations may offer a lower configurable operational cap,
but MUST NOT silently lower stored KDF parameters. Memory allocation/unsupported-algorithm
failure is an unlock error, not permission to use weaker parameters. The selected library
must expose Argon2id directly and fail closed when its crypto backend lacks support
([cryptography Argon2id API](https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/)).

Legacy scrypt parameters are immutable compatibility constants. A legacy password is used
only to authenticate/decrypt the old candidate in memory. Migration then creates new random
v3 salt/nonces/DEK; it never treats the legacy derived key as a DEK or stores it in v3.

## 5. KEK/DEK envelope encryption and rotation

- A CSPRNG creates a 32-byte DEK. The DEK encrypts the JSON payload with AES-256-GCM.
- Argon2id derives a 32-byte password KEK. The KEK wraps only the DEK with AES-256-GCM in a
  password slot. Password, KEK, and plaintext are never serialized or logged.
- Password/KDF rotation creates a new salt, KEK, nonce, and slot. A transition candidate may
  contain both old and new slots until the new password has unlocked and validated it. A
  second atomic transaction removes the old slot; failures retain a recoverable old slot.
- DEK rotation creates a new DEK and payload nonce, re-encrypts the payload, wraps the new
  DEK into approved slots, and validates the complete candidate before activation.
- A password rotation does not make old backups unreadable by the old password. Retiring
  those backups is a separate, explicit destructive decision; reliable secure deletion on
  SSDs is not claimed.

Every rotation is an atomic storage transaction with a journal/receipt, pre-operation backup,
post-write decrypt-and-schema validation, and a tested recovery command. Errors never mutate
the in-memory live generation or remove the last usable slot.

## 6. Atomic storage, backups, and crash recovery

All vault, encrypted conflict, migration receipt, and sync-journal writes go through one
storage abstraction. The 5a implementation order is:

1. Acquire an exclusive per-vault lock with owner/process identity and bounded stale-lock
   recovery. Re-read the generation/digest after locking to prevent lost updates.
2. Create an owner-only, unpredictable temporary file in the destination directory with
   exclusive creation. Write complete bytes, flush, and `fsync`/`FlushFileBuffers`.
3. Read the temporary file back through the strict parser, authenticate/decrypt it, and check
   payload invariants. Faults leave the live file untouched.
4. Preserve the last known-good live bytes under a unique, non-overwriting backup name. On
   Windows use `ReplaceFileW` with a backup where supported; Microsoft documents replacement
   plus optional backup as one operation
   ([ReplaceFileW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew)).
   On POSIX, create and sync the backup before same-filesystem `os.replace`.
5. Atomically replace the destination, then sync the resulting file and parent directory
   where supported. Python requires flushing before `os.fsync`, and a successful POSIX
   `os.replace` is atomic ([Python `os` documentation](https://docs.python.org/3/library/os.html)).
6. Re-open and validate the live file, mark the journal committed, release the lock, and only
   then apply retention. Migration backups are exempt from automatic retention.

Recovery classifies live, temp, backup, and journal candidates by authenticated vault ID,
generation, digest, and transaction ID. It never chooses solely by modification time. If one
valid newest candidate is unambiguous it may offer recovery; ambiguity is read-only and asks
the user. Recovery first copies the current evidence, supports `--dry-run`, and uses the same
atomic primitive. No cleanup path deletes the only valid candidate.

## 7. Keyring trust boundary

The current raw-master-password keyring entry is deprecated but remains readable until an
explicit 5e transition. V3 MUST NOT add or update raw password entries.

An optional device-unlock slot stores a random 32-byte device KEK in an approved OS keyring;
the file holds only the corresponding authenticated wrapped DEK. The keyring account name is
scoped by `vault_id` and slot ID, not a global `master-password` label. Backend discovery MUST
allowlist supported OS facilities (Windows Credential Locker initially), reject null/plaintext
or unreviewed third-party backends, and fail closed without falling back to a file or
environment variable. The upstream keyring documentation notes that backend security
considerations vary and that no analysis is published for its Windows backend
([keyring security considerations](https://keyring.readthedocs.io/en/stable/#security-considerations));
therefore this is a convenience boundary, not a second authentication factor.

Any process running as the same unlocked OS user may be able to request the device secret.
Keyring unlock does not defend against same-user process compromise, administrator/kernel
compromise, or theft of an already unlocked session. UI text MUST explain this before opt-in.
Disablement first atomically removes the device slot from the vault and validates password
unlock, then deletes the keyring entry; a failed keyring deletion is reported for manual
cleanup. The reverse order is used when enabling: create keyring secret, build/validate the
candidate slot, activate atomically, and remove the secret if activation fails.

The optional rollback anchor is a distinct keyring record with no DEK/KEK/password. Losing it
reduces rollback detection but MUST NOT destroy password-based recovery.

## 8. Multi-source sync, conflicts, and deletion

`linked_sources` plus one `sync_status` cannot represent independent progress across several
replicas. The 5f model adds an encrypted per-entry ledger:

- stable local entry ID and content revision ID;
- per-source replica link, adapter capability set, last accepted remote revision/token (when
  trustworthy), canonical content fingerprint, and encrypted base snapshot;
- per-source pending operation ID/state and last acknowledged local revision;
- a tombstone with deletion revision, creation time, required acknowledgements, and retention
  deadline.

Pull uses a three-way comparison of local, last accepted base, and remote. Only-local or
only-remote change can advance automatically. Concurrent differing changes create an
encrypted conflict snapshot; `primary` is a UI recommendation, never permission to silently
choose for password, notes, deletion, or source-link changes. Sources without trustworthy
revision tokens use canonical fingerprints and conservatively conflict when causality is
unknown.

Remote absence is not automatically deletion. It becomes a deletion observation only after
an adapter declares an authoritative complete listing and its documented delete semantics.
Otherwise it is `unknown/missing` and cannot purge local data. A local delete creates a
tombstone before remote calls. The tombstone remains until every enabled linked replica has
acknowledged deletion (or the user explicitly abandons a replica) and the retention period
has elapsed. Disabled, unavailable, and partially failed sources remain pending. Purge is a
separate atomic transaction.

Remote writes follow a durable saga: persist intent, invoke the adapter with an idempotency
key when supported, read back/reconcile, then record acknowledgement. After a crash, unknown
outcomes are reconciled before retry so `create` is not blindly duplicated. Adapter
capabilities (`authoritative_list`, `revision_token`, `idempotent_create`, `delete_confirm`)
are explicit and tested. Sync never holds plaintext longer than the adapter call and never
writes it to logs, receipts, preferences, or operation IDs.

## 9. Migration and rollback protocol

`vault migrate-v3` is explicit and operates only on user-selected paths. Its default is
`--dry-run`; dry-run performs read-only format detection, authentication, schema validation,
resource estimates, free-space checks, and reports intended paths without creating files.

Execution requires a second explicit flag and follows this state machine:

```text
legacy live -> immutable byte backup -> validated v3 candidate
            -> explicit activation -> validated v3 live + recovery receipt + legacy backup
```

The receipt contains no secrets: transaction/vault IDs, source and destination formats,
digests, generations, timestamps, and backup path. A candidate is activated only after both
legacy and v3 decrypt to the same normalized payload, including entry IDs, secret fields,
links, tombstones, and conflict metadata. The source legacy file is never edited in place.

Rollback validates the receipt, current file, and backup digest; preserves the current v3
file as evidence; and atomically restores a copy of the legacy bytes. Missing/mismatched
artifacts stop for manual recovery. No release may auto-run migration, remove a backup, or
change the default creation format without separate authorization and release review.

## 10. Required tests and implementation sequence

Every implementation PR uses only generated fake vault fixtures in isolated temporary
directories. Production randomness is tested through invariants; deterministic known-answer
vectors inject fixed fake password/salt/nonces/DEK only through test-only constructors.

Required gates include:

- frozen v1 and v2 fake fixtures remain byte-readable; read/dry-run leaves hash and metadata
  unchanged; legacy save never becomes v3;
- cross-platform Argon2id and wrap/payload known-answer vectors;
- flip/truncate/extend every framing, header, slot, AAD, ciphertext, and tag region;
- reject oversized lengths/KDF work, duplicate keys, bad encodings, unknown versions, and
  v3-magic downgrade without legacy fallback;
- wrong password, swapped slots/vault IDs, generation rollback with/without anchor, nonce
  uniqueness, and tamper/property tests;
- fault injection before and after every write, flush, backup, replace, validation, journal,
  and cleanup boundary, followed by deterministic recovery;
- concurrent writers, stale locks, disk-full/permission failures, and no lost update;
- migration interruption at every state, payload equivalence, dry-run zero writes, rollback,
  and retention of the only valid copy;
- multi-source concurrent edit/delete, partial listing, missing timestamps, duplicate create,
  crash-after-remote-write, disabled/unavailable source, tombstone acknowledgement, and
  deterministic conflict tests;
- log/API/exception snapshots prove no password, entry secret, KEK, DEK, keyring secret, or
  decrypted conflict escapes.

Implementation remains six independently reviewed and merged PRs, in order:

1. **5a atomic storage and crash recovery** for legacy vault/conflict/prefs writes; no format
   or KDF change.
2. **5b format parser/read-only compatibility framework** with strict discrimination and no
   automatic migration.
3. **5c Argon2id + KEK/DEK v3** and fake known-answer vectors; v3 creation is explicit.
4. **5d explicit migration, backup, dry-run, activation, and rollback**, never startup-driven.
5. **5e keyring boundary**, device slot, legacy-keyring transition, and rollback anchor.
6. **5f sync/conflict/deletion model** with adapter capabilities and durable operation ledger.

Each PR runs Python tests/audit, frontend lint/build/audit, Rust test/check/audit, Windows
target checks, and GitHub CI. An irreversible migration, real-vault operation, default-format
flip, tag, or release is a stop point requiring explicit owner authorization.
