# Vault format compatibility framework

Vault Format v3 is structurally parsed before any KDF work. The 5c implementation can create,
decrypt, and update an explicitly created v3 file, but does not migrate legacy files or change
the default format. Cryptographic details and commands are documented in
[`vault-v3-cryptography.md`](vault-v3-cryptography.md).

## Discrimination rules

- Bytes that do not begin with the framed-family prefix `VLTUV` are legacy v1/v2 candidates
  and continue through the fixed scrypt/AES-GCM compatibility reader.
- Any `VLTUV*` prefix is a framed Vault Unified file. Only the complete `VLTUV3\r\n` magic is
  accepted. Unknown, truncated, or damaged family versions fail closed and never fall back
  to scrypt.
- A valid v3 frame is parsed strictly, then must authenticate through the v3 path. Ordinary
  writes preserve the detected format and never fall back to or convert through legacy.
- Format inspection does not request a password, derive a key, expose salts/nonces/wrapped
  keys, or change file bytes/metadata.

```powershell
.\vault.cmd format inspect --vault-path C:\path\to\secrets.vault
```

The command reports only kind/version, payload schema, generations, vault ID, cipher, slot
count/types, and KDF name. It also reports `authenticated: false`: without a password this
metadata is untrusted structural input, not proof of vault identity, freshness, or integrity.

## Parser limits

The parser checks the 8-byte magic and 4-byte big-endian header length before JSON decoding.
It caps the complete file at 256 MiB and the header at 64 KiB. JSON uses strict UTF-8,
rejects duplicate/unknown fields, and requires canonical UUID and unpadded base64url
encodings. Declared ciphertext length must equal the remaining frame exactly.

V3 password slots are limited to eight. The parser accepts only AES-256-GCM and Argon2id
version 19 with a 32-byte output, 16-32 byte salt, 64-256 MiB memory, 1-6 passes, 1-4 lanes,
and at most 768 MiB-passes of work. These checks happen before any KDF call.
Optional extension fields live inside a bounded `extensions` object, require namespace-qualified
lowercase names, and allow only bounded scalar values.

## Compatibility and rollback

Legacy encryption and payload versions are unchanged. Merely opening or inspecting a legacy
vault is byte-for-byte read-only, and ordinary legacy writes remain legacy. V3 creation is
available only through `vault init-v3` and refuses an existing path. There is no migration in
5c, so no existing user file is converted or needs format rollback. Pre-v3 applications cannot
open an explicitly created v3 file; its retained atomic backups therefore remain important.
