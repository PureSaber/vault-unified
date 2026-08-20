# Vault format compatibility framework

This stage recognizes Vault Format v3 structure but does not yet create, decrypt, migrate,
or overwrite v3 files. Argon2id and KEK/DEK cryptography arrive in the separate 5c PR.

## Discrimination rules

- Bytes that do not begin with the framed-family prefix `VLTUV` are legacy v1/v2 candidates
  and continue through the fixed scrypt/AES-GCM compatibility reader.
- Any `VLTUV*` prefix is a framed Vault Unified file. Only the complete `VLTUV3\r\n` magic is
  accepted. Unknown, truncated, or damaged family versions fail closed and never fall back
  to scrypt.
- A valid v3 frame is parsed read-only. Existing legacy writers refuse to overwrite it.
- Format inspection does not request a password, derive a key, expose salts/nonces/wrapped
  keys, or change file bytes/metadata.

```powershell
.\vault.cmd format inspect --vault-path C:\path\to\secrets.vault
```

The command reports only kind/version, payload schema, generation, vault ID, cipher, slot
count/types, and KDF name. It also reports `authenticated: false`: without a password this
metadata is untrusted structural input, not proof of vault identity, freshness, or integrity.

## Parser limits

The parser checks the 8-byte magic and 4-byte big-endian header length before JSON decoding.
It caps the complete file at 256 MiB and the header at 64 KiB. JSON uses strict UTF-8,
rejects duplicate/unknown fields, and requires canonical UUID and unpadded base64url
encodings. Declared ciphertext length must equal the remaining frame exactly.

V3 password slots are limited to eight. The 5b parser accepts only AES-256-GCM and Argon2id
version 19 with a 32-byte output, 16-32 byte salt, 64-256 MiB memory, 1-6 passes, 1-4 lanes,
and at most 768 MiB-passes of work. These checks happen before 5c performs any KDF call.
Optional extension fields live inside a bounded `extensions` object, require namespace-qualified
lowercase names, and allow only bounded scalar values.

## Compatibility and rollback

Legacy encryption and payload versions are unchanged. Merely opening or inspecting a legacy
vault is byte-for-byte read-only. There is no production v3 serializer in 5b, so this stage
cannot accidentally create a new-format vault. Reverting the PR restores the old parser; any
synthetic v3 test fixture remains unsupported and no user file requires migration or rollback.
