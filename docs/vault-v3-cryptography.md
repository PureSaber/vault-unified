# Vault Format v3 cryptography

Vault Format v3 is an explicit opt-in format. It uses Argon2id to derive a key-encryption
key (KEK), a random data-encryption key (DEK), and AES-256-GCM for both DEK wrapping and
payload encryption. This implementation does not migrate a legacy file, change the default
format, create a release, or read/write a raw v3 password in the OS keyring.

## Create and open

New v3 creation requires an explicit command and refuses an existing destination:

```powershell
.\vault.cmd init-v3 --vault-path C:\isolated\new.vault
```

Omit `--password` to use the hidden confirmation prompt. The command never reads a saved
legacy master password and never offers to remember the v3 password. Once explicitly
created, the ordinary local-vault read/edit path preserves v3 and uses the atomic writer.
The existing `vault init`, setup wizard, and automatic missing-file creation remain legacy
scrypt/AES-GCM for compatibility.

The payload is canonical UTF-8 JSON with schema `{"version":2,"entries":{...}}`. Creation
and opening enforce the 256 MiB file limit, 32-level JSON depth limit, 100,000-entry limit,
and a 1-1,024 byte UTF-8 password limit. Duplicate JSON fields, non-finite numbers, reference
cycles, malformed UTF-8, and schema extensions outside the encrypted entry values fail
closed.

## Algorithms and authenticated fields

New password slots use the memory-constrained second recommendation from
[RFC 9106](https://www.rfc-editor.org/rfc/rfc9106.html): Argon2id v19 with 65,536 KiB memory,
three passes, four lanes, a random 16-byte salt, and a 32-byte output. `cryptography>=44` is
required because that release introduced its Argon2id API
([cryptography changelog](https://cryptography.io/en/latest/changelog/#v44-0-0)). A backend
that cannot provide Argon2id fails; parameters are never weakened at runtime.
KDF calls are serialized by a process-wide lock so concurrent requests cannot multiply the
64 MiB allocation without bound.

Each new vault has random UUIDs for the vault, DEK, and password slot; a random 32-byte DEK;
and separate random 96-bit nonces for wrapping and payload encryption. AES-GCM nonce reuse
under the same key is forbidden, consistent with the
[cryptography AES-GCM warning](https://cryptography.io/en/stable/hazmat/primitives/aead/).

AAD is deterministic length-prefixed binary data derived from the validated header:

- DEK wrapping authenticates the format/cipher, vault and DEK IDs, key generation, slot ID
  and type, all Argon2 parameters, wrap cipher, and wrap nonce.
- Payload encryption authenticates the format/cipher, vault and DEK IDs, content generation,
  payload schema and nonce, plaintext/ciphertext lengths, and a canonical extensions digest.

Changing a bound field, wrapped DEK, payload ciphertext, or tag causes a normalized
authentication error. A v3 failure never falls back to the legacy KDF.

The checked-in known-answer vector at `tests/fixtures/v3-known-answer.json` contains only an
explicit fake password, fake entry, fixed IDs, fixed salt/nonces/DEK, the expected framed
bytes, and SHA-256. Production code always obtains these values from the OS CSPRNG.

## Updates and key rotation

Every authenticated content update increments `generation`, creates a fresh payload nonce,
preserves the DEK and `key_generation`, validates the candidate, and atomically replaces the
live file while retaining its prior bytes as a unique backup. The replacement includes a
compare-and-swap check of the source SHA-256 while holding the storage lock; a concurrent
change fails instead of being overwritten. Explicit creation similarly rechecks that the
destination is absent after acquiring the lock.

The following operations are explicit and never consult raw-password keyring state:

```powershell
.\vault.cmd v3 rotate-password --vault-path C:\isolated\new.vault
.\vault.cmd v3 rotate-dek --vault-path C:\isolated\new.vault
```

Password rotation authenticates the old slot and payload, derives a new KEK from a fresh
salt, uses a fresh wrapping nonce, increments `key_generation`, and rewraps the same DEK.
The payload ciphertext and content generation do not change. DEK rotation creates a fresh
DEK/ID, salt, wrapping nonce, and payload nonce; re-encrypts the payload; and increments both
generations.

Atomic backups deliberately remain decryptable with the password/key state that was active
before rotation. This is the recovery path, not secure deletion. Backup retirement remains
an explicit future decision; SSD secure deletion is not claimed.

## Failure and compatibility boundaries

- Candidate bytes are parsed, decrypted, and schema-validated before activation and again
  after replacement. Interrupted transactions fail closed into the existing `vault storage
  inspect` and dry-run-first `vault storage recover` flow.
- Whole-file replay of an older valid generation cannot be detected from the file alone.
  The explicitly enabled external rollback anchor is described in
  [`vault-v3-keyring.md`](vault-v3-keyring.md).
- Python immutable strings/bytes cannot be reliably zeroized. Password and key lifetimes are
  minimized, but a compromised unlocked process remains outside this protection boundary.
- Password unlock requires exactly one password recovery slot. One separately authenticated
  device slot may coexist with it; duplicate/ambiguous slots fail closed. Password or DEK
  rotation refuses to run while a device slot exists, so it can never silently discard that
  slot. Disable device unlock explicitly, rotate, and re-enable it.
- Legacy conversion is available only through the separately reviewed, dry-run-first 5d
  workflow in [`vault-v3-migration.md`](vault-v3-migration.md). It preserves exact legacy
  bytes, a validated candidate, a recovery receipt, and an explicit rollback path.

The broader compatibility, rollback, storage, and threat assumptions remain normative in
[`vault-v3-threat-model.md`](vault-v3-threat-model.md) and
[`atomic-storage-recovery.md`](atomic-storage-recovery.md).
