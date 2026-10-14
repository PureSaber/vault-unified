# Personal vault development plan

The owner authorized all twenty directions below on 2026-10-04, with autonomous
implementation, self-review and repair after each increment, and owner acceptance
only after development. This is post-v1.3 development. The released v1.3 assets
and its historical acceptance remain unchanged. No new release is implied by a
passing source test.

The complete scope is retained here across development sessions. A feature is
complete only when its user workflow, failure behavior and appropriate automated
or runtime evidence have been inspected. Tests of a mock do not prove native
integration or live distribution. External prerequisites must be recorded rather
than replaced with a simulated completion claim.

| # | Outcome and acceptance scope | Status / evidence |
|---|---|---|
| 1 | Chrome / Edge import: source guidance, format detection, faithful fields, duplicate review, invalid rows, cancel, apply, undo, password-page entry point | Merged in PR #58 / `6cf4237`; CI run 37187313246 passed; source feature, not yet released |
| 2 | Persistent trusted-browser authorization, desktop discovery, locked-state denial, restart reconnection and device revocation | Implemented on `codex/browser-trusted-devices`; local backend, Windows credentials and real native/extension/API restart checks passed; integration CI pending |
| 3 | Inline account choice, keyboard filling, multi-step/dynamic forms, explicit handling of complex forms | Pending |
| 4 | System-wide quick search and copy, keyboard navigation, tray and window lifecycle | Pending |
| 5 | TOTP setup including QR, current code/countdown/copy and browser filling | Pending |
| 6 | Recoverable trash and archive, clear retention/permanent-delete behavior, exclusion from normal fill | Pending |
| 7 | Local weak/reused-password findings and actionable change-password workflow; optional privacy-preserving exposure checking | Pending |
| 8 | Encrypted, bounded generated-password recovery; passphrases and configurable website character restrictions | Pending |
| 9 | Favorites, tag/type filters, sorting and efficient keyboard search | Pending |
| 10 | Windows Hello device authorization and fallback, OS lock and suspend integration | Pending |
| 11 | Multiple URLs per account, explicit matching and exclusion rules | Pending |
| 12 | Extension distribution, desktop update flow, version compatibility, signing and preserved-vault upgrade validation | Pending |
| 13 | In-vault duplicate review and field merge, bulk tagging/archive with safe preview/apply | Pending |
| 14 | Understandable history comparison and selective field restoration | Pending |
| 15 | New-computer migration and isolated restore rehearsal using existing backup/recovery mechanisms | Pending |
| 16 | User-triggered Windows application auto-type with verified destination and configurable sequences | Pending |
| 17 | Practical templates for recovery codes, software licenses and API credentials, including used-code tracking | Pending |
| 18 | Full-vault encrypted cross-computer synchronization over user-controlled storage, concurrent-edit conflict resolution | Pending |
| 19 | Browser passkey creation and sign-in, storage, recovery and migration lifecycle | Pending |
| 20 | Encrypted single-item sharing with expiry/access limits/revocation, then household shared-vault workflow and permissions | Pending |

## Working method

- Reuse the existing vault, preview/apply, backup, history and authentication
  boundaries. Add no redundant baseline manifests or release hashing runs.
- Use generated credentials and isolated files only. Preserve user-owned
  untracked extension artifacts and never inspect private keys or real vaults.
- Implement coherent increments on `codex/` branches, self-review each diff and
  run relevant regressions; run required full checks before PR integration.
- Keep Chinese and English flows aligned. Preserve rollback compatibility for
  additional encrypted metadata and never silently discard older data.
- Record actual evidence below. Do not mark the overall goal complete while any
  row is pending, partly implemented, externally blocked, or insufficiently tested.

## Increment evidence

The starting source is `b88b328` (PR #57). Browser saving and same-run reconnection
already exist there; they are not a replacement for rows 2, 3, or 8.

### Browser import increment

- Real API/encrypted-vault tests cover both browser CSV variants, UTF-8 BOM,
  reordered headers, multiline/Unicode values, invalid records, repeated import,
  cancel, apply and undo. Browser updates retain absent personal fields and
  attachments; distinct Unicode passwords are not collapsed as duplicates.
- The full local Python run reached 325 passing cases and one CI action-count
  mismatch from adding Python to the renderer job. The expectation was updated
  for that actual new step, then all 28 import/workflow cases passed.
- All 48 renderer tests passed, including two new real-API import journeys,
  Chinese/English behavior, keyboard file selection, accessibility, and reopening
  the imported vault after lock. The artifact scan removed zero files.
- Self-review fixed partial browser updates clearing personal-only fields and
  made the file picker keyboard reachable. A test-only request proxy was replaced
  with direct renderer/API requests; only runtime-config handoff is substituted.
- The local dependency audit found an older urllib3 in the development venv;
  updating it to 2.8.0 produced a clean audit. No application dependency was added.
- Generated preview screenshot and accepted-format/rollback details are in
  [browser-password-import.md](browser-password-import.md). Native installer and
  independent human acceptance remain part of later delivery/final acceptance.

### Trusted browser increment

- Device identity is an extension-scoped non-exportable signing key; desktop
  public identities use the existing approved Windows Credential Manager.
  Access tokens remain session-only, and proofs only access already-unlocked
  matching vaults. Revocation also invalidates outstanding access tokens.
- Native Messaging returns only the live loopback address and instance ID. The
  desktop registers exact Chrome/Edge origins on pairing. No vault format change,
  port scanning, persistent bearer tokens or new backup/hash manifests were added.
- Local full Python suite: 345 passed. Following final storage/CI edits, all 24
  trust/discovery/workflow cases passed. Rust unit tests: 3 passed; native debug
  executable built. Python dependency audit: no known vulnerabilities.
- Full UI suite: 48 passed; after adding storage-error recovery and refining
  reconnect UI, all 20 focused extension journeys passed. Artifact scan removed
  zero files. The generated device-list screenshot was visually inspected.
- The actual Chromium extension, Windows credential store, native executable
  and isolated API passed a restart with changed port, locked-state denial,
  private-key export refusal, real credential filling, manual address fallback
  with native discovery disabled, and desktop revocation. No real browser profile
  or production native-host registry key was used. This journey is included in CI.
- Self-review added bounded native reads, separated persistent device revocation
  from temporary session cancellation, and preserved retry/manual-address paths
  when device storage or native discovery is unavailable.
- See [trusted-browser-connections.md](trusted-browser-connections.md) for trust,
  rollback and test boundaries. Installed application lifecycle, native-host
  removal during uninstall and new release delivery remain tracked in row 12.
