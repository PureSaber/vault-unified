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
| 2 | Persistent trusted-browser authorization, desktop discovery, locked-state denial, restart reconnection and device revocation | Merged PR #59 / `6518339`; full CI run 38497981145 passed, including actual native restart journey; source feature, not yet released |
| 3 | Inline account choice, keyboard filling, multi-step/dynamic forms, explicit handling of complex forms | Pending |
| 4 | System-wide quick search and copy, keyboard navigation, tray and window lifecycle | Pending |
| 5 | TOTP setup including QR, current code/countdown/copy and browser filling | Pending |
| 6 | Recoverable trash and archive, clear retention/permanent-delete behavior, exclusion from normal fill | Merged PR #61 / `565f4d7`; full CI 38501649498 passed; source feature, not released |
| 7 | Local weak/reused-password findings and actionable change-password workflow; optional privacy-preserving exposure checking | Pending |
| 8 | Encrypted, bounded generated-password recovery; passphrases and configurable website character restrictions | Pending |
| 9 | Favorites, tag/type filters, sorting and efficient keyboard search | Merged with account organization in PR #61; full CI passed |
| 10 | Windows Hello device authorization and fallback, OS lock and suspend integration | Pending |
| 11 | Multiple URLs per account, explicit matching and exclusion rules | Pending |
| 12 | Extension distribution, desktop update flow, version compatibility, signing and preserved-vault upgrade validation | Pending |
| 13 | In-vault duplicate review and field merge, bulk tagging/archive with safe preview/apply | Merged PR #63 / `95d126a`; exact-head CI 38504714200 passed; bulk actions previously merged in #61 |
| 14 | Understandable history comparison and selective field restoration | Merged PR #62 / `30a3e05`; exact-head CI 38503677441 passed, including all 54 UI journeys |
| 15 | New-computer migration and isolated restore rehearsal using existing backup/recovery mechanisms | Pending |
| 16 | User-triggered Windows application auto-type with verified destination and configurable sequences | Pending |
| 17 | Practical templates for recovery codes, software licenses and API credentials, including used-code tracking | Implemented on `codex/credential-templates`; relevant backend and real English/Chinese renderer journeys passed; integration pending |
| 18 | Full-vault encrypted cross-computer synchronization over user-controlled storage, concurrent-edit conflict resolution | Pending |
| 19 | Browser passkey creation and sign-in, storage, recovery and migration lifecycle | Pending |
| 20 | Encrypted single-item sharing with expiry/access limits/revocation, then household shared-vault workflow and permissions | Pending |

## Working method

The owner approved the complete personal-edition plan on 2026-10-14: local first,
optional networking, Windows desktop and Chrome/Edge extension, plus a separately
deployable sharing service. No Vault Unified cloud account is required.

Implementation proceeds in seven stages: (1) browser integration and payload
compatibility; (2) organization/recovery/templates; (3) daily login, TOTP,
generation, website rules and Windows integration; (4) health checks and migration;
(5) encrypted folder/WebDAV synchronization; (6) passkeys and sharing;
(7) matching installers/extension, signed updates and final acceptance.

Defaults and scope:

- Keep Python/FastAPI, React/Tauri and the v3 cryptographic container. Enable the
  new payload only after retaining an encrypted pre-upgrade backup; older clients
  reject the new payload schema. New-format backup/recovery must preserve all data.
- Trash retains items for 30 days; archived items remain until explicitly removed.
  Both are excluded from normal filling. Generated history keeps at most 100
  records for at most 30 days, encrypted in the vault.
- Website rules default to exact hosts. Site permissions are optional and explicit;
  cross-origin frames need separate authorization. Never submit login automatically.
- Hello follows a master-password unlock on every app launch, and uses real Windows
  key protection. Lock/suspend locks the vault. Auto-type stops on destination focus
  change and defaults to username, Tab, password without Enter.
- Folder/WebDAV sync shares an encrypted per-device change protocol with field
  merges, explicit conflicts and acknowledged deletion records. Attachments, TOTP,
  history and passkeys travel; browser trust and Hello credentials stay local.
- Passkeys support creation/sign-in, origin/RP checks, confirmation, cancel/timeout,
  encrypted backups and Vault Unified device migration. External-manager passkey
  conversion is deferred.
- Sharing runs as a separate FastAPI/SQLite service with a browser viewer and
  Python/Docker Compose deployment. Single-item sharing has expiry, access limits
  and revocation. Household vaults have owner/editor/reader roles, invitations
  bound to local identities, and key rotation on removal.
- Network sync, sharing, exposure checks and automatic update checks are opt-in.
  Tauri update signatures are included. Commercial Authenticode, store listing,
  public server/domain deployment, mobile apps and new external connectors are
  outside this delivery.
- Final delivery includes installers, the matching extension, service deployment
  package, migration instructions and concise acceptance steps. Native Hello user
  authentication is concentrated in final acceptance.

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

### Personal payload compatibility

- Schema 3 adds encrypted vault-wide metadata while keeping the v3 crypto
  container and schema 2 known-answer vectors. Old readers reject the new schema;
  accidental downgrade and schema/header mismatch are refused.
- An explicit preview/cancel/apply flow pins an encrypted old-format backup before
  migration. Legacy and framed vaults are covered; existing framed device slots
  survive. Changed previews and backup/replacement failures preserve prior data.
- Entry writes, import undo, password changes and emergency recovery preserve the
  complete payload. The upgrade locks all sessions before reopening.
- Local full Python suite: 353 passed; after adding device-slot, write-failure and
  API stale-preview coverage, all 16 focused payload/backup cases passed. All 51
  UI journeys passed, including real-API English/Chinese upgrade and accessibility.
  Rust tests: 3 passed; TypeScript/build passed; Python audit and secret scan clean.
- Merged PR #60 / `38b88e1`; exact-head CI 38499628516 passed. See
  [personal-payload-upgrade.md](personal-payload-upgrade.md). This enables later
  features' storage and does not mark those features complete.

### Account organization

- New vaults create schema 3 directly; existing vaults retain the explicit upgrade.
- Trash, archive, restore, favorite, tag/type filters, sort and batch tagging use
  the existing transaction and session-bound preview mechanism. Browser candidates
  exclude archive/trash; remote metadata refresh preserves these local states.
- Expired trash removes credential content and sync base snapshots while retaining
  deletion acknowledgements. Archive stays indefinitely. Encrypted backups retain
  complete data; plaintext export explicitly includes active entries only.
- Self-review/runtime work fixed a category-switch response race and the existing
  CSV export attachment-column error. Full local Python suite: 361 passed, followed
  by passing focused organization/retention checks after the final snapshot repair.
- Full UI run: 52 passed and one generated-API teardown race. Waiting for the
  unlock backup refresh before shutting down that test API fixed it; both focused
  organization journeys then passed, including accessibility and artifact scan.
  The generated screenshot was visually inspected and the search/filter widths
  corrected. Exact-head CI 38501649498 passed; merged PR #61 / `565f4d7`.
- See [account-organization.md](account-organization.md). Duplicate merging,
  history field selection and templates remain stage 2 work.

### History field restore

- The history comparison shows current-draft and saved values for changed fields,
  with per-field selection. Loading selected fields stays in the draft until the
  existing atomic Save; current unselected fields and attachments remain intact.
- Passwords, notes, authenticator keys and custom values are hidden by default,
  with explicit reveal, timeout and blur/visibility hiding. The modal supports
  keyboard focus and Escape cancellation; old confirmation-only copy was removed.
- Existing six transactional-editor journeys and the real isolated API selective
  password/title restore passed, including persistence, cancellation, accessibility
  and artifact scanning. The full renderer suite exposed a generated-sidecar
  teardown race (an import cancellation was still in flight at process shutdown).
  Waiting for a fresh request-quiet interval fixes teardown without suppressing
  errors; all seven real-API journeys passed afterwards. TypeScript/build passed.
  Exact-head CI 38503677441 passed, including all 54 UI journeys, full Python,
  native desktop and dependency audits. Merged PR #62 / `30a3e05`.
- See [history-field-restore.md](history-field-restore.md). No additional backend
  approval, hashing or persistence mechanism was introduced.

### Duplicate account merge

- Exact website/username candidate filtering, per-field choice and a final
  preview/confirmation merge two active logins. The original source goes to
  recoverable trash; both histories and attachments remain in the kept entry.
- Merged versions live in an encrypted schema-3 namespace outside ordinary edit
  history retention. Attachment identity collisions are repaired and capacity
  limits refuse the whole operation without discarding data.
- All 28 focused Python cases passed before the final attachment-reference and
  legacy-refusal additions. Four real-API organization/history/merge journeys
  passed, including accessibility and artifact scan; the screenshot was inspected.
  Full local Python: 368 passed. Exact-head CI 38504714200 passed, including all
  55 renderer journeys, Python, native desktop and audits. Merged PR #63 / `95d126a`.
- See [duplicate-account-merge.md](duplicate-account-merge.md).

### Credential templates

- Recovery codes have individual encrypted values and used timestamps. Copy is
  separate from editing, refuses used codes, and uses existing clipboard clearing.
  Software licenses and API credentials have dedicated key/detail forms.
- Schema-3 checks cover saves and imports. History comparisons/restoration and
  duplicate field choices include template details. JSON v2 and CSV preserve
  template data; old JSON v1 remains readable and absent template fields in old
  imports do not erase current data. Recovery packages preserve everything.
- Eight initial template cases and 46 existing editor/import/personal/merge
  backend cases passed. After compatibility refinements, 32 template/import cases
  passed. Fifteen renderer journeys passed, including English/Chinese templates,
  used-code persistence, discard, existing editors, accessibility and artifact
  scan. Screenshot inspected; TypeScript/build and secret scan passed.
- Exact-head full CI is required before integration. See
  [credential-templates.md](credential-templates.md).

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
