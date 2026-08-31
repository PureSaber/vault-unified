# Backup retention and restore center

Vault Unified keeps the existing atomic writer's encrypted recovery backups and adds an
explicit desktop management layer. Nothing in this feature schedules background deletion.

## Backup types

- **Local atomic backup:** `<vault>.bak.<transaction-id>` beside the active vault. It is the
  exact encrypted active bytes from before one atomic replacement.
- **Manual backup:** an exact encrypted copy created in the default backup directory or a
  user-selected regular directory. Manual paths are registered in a secret-free local
  catalog.

The catalog contains paths and pin state only. It never contains vault passwords, decrypted
entries, encryption keys, tokens, or copied ciphertext.

## Verification

Each displayed backup records size, modification time, SHA-256, detected vault format, and
whether the current credential can authenticate and decrypt it. Older password or key
rotations can make a valid backup appear unverified with the current credential. Such a file
is retained; it can be restored by supplying its older password.

The **Verify latest backup** action is read-only with respect to the active vault: it reads,
authenticates, decrypts, and parses the selected backup, then records only a non-secret health
result. Testing a backup destination creates and removes a short-lived generated probe file so
the app can report existence, writability, and free space; no vault content is written there.

## Persistent health status

The optional, namespaced `backup_health.v1.json` sidecar records only timestamps, fixed error
summaries, verification state, and whether a recovery kit was created. The existing
`personal_settings.json` schema remains unchanged, so rolling back to v1.2 is safe and an older
release simply ignores the new file. Missing health state loads with safe defaults. Passwords,
recovery codes, vault contents, tokens, and exception details are never stored in this status.
A successful backup clears the previous backup error; an automatic-backup error remains
visible until a later success or explicit correction.

## Retention policy

Cleanup is always preview-first. The default policy keeps:

- the newest 10 verified local atomic backups;
- one verified local atomic backup per day for 30 days;
- one verified local atomic backup per ISO week for 12 weeks.

A backup is never selected automatically when it is:

- a registered manual backup;
- pinned by the user;
- not authenticated by the current credential;
- not a regular file;
- outside the exact local atomic filename pattern.

Applying a preview rereads every candidate, compares its SHA-256 with the preview, authenticates
it again, and only then unlinks it. Changed or ambiguous evidence produces an error and remains
on disk.

## Restore

Restore is a two-phase operation and accepts an optional old backup password. The read-only
preview authenticates and parses the source, records its SHA-256, and binds a random five-minute
token to the authenticated desktop scope, active vault file digest, logical state digest, and
in-memory generation. Neither the password nor the recovery code is stored in the preview.

Applying a restore requires the single-use token and an explicit confirmation. It:

1. authenticates the selected registered or local atomic backup;
2. rejects a changed source, active vault digest, logical state, generation, session, expired
   token, or replay;
3. atomically replaces the active vault;
4. retains the displaced active bytes as a fresh atomic backup;
5. reopens the committed vault before reporting success;
6. invalidates the current desktop session so the restored vault must be unlocked again.

Restore never silently overwrites an active vault without retaining its prior encrypted bytes.
A failed password, changed candidate, missing file, storage lock, or failed post-commit open
leaves the user with an error rather than silently continuing with stale in-memory entries.
Startup backup restore and emergency-kit recovery use the same preview/apply rule. When no
unlocked vault session exists, the preview is bound to the authenticated per-process desktop
sidecar instance. Emergency recovery also checks the active encrypted-file digest again before
replacement and uses the atomic writer to retain the displaced bytes.

## Preview-confirmed cleanup

Desktop backup cleanup is a two-phase operation. A dry-run issues a random, single-use token
that expires after five minutes and belongs to one unlocked session. Applying cleanup requires
that token and the exact same retention policy. The server deletes only the paths and SHA-256
digests present in the approved preview; backups created after preview are never added to the
execution set. A candidate that was changed, pinned, removed, or became unverifiable is skipped
with an error instead of being deleted.
