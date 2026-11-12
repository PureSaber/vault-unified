# UI/UX finishing pass — issue #93

Base: `c219a7b` (main); implementation branch: `feat/uiux-finish-93`.

## Delivered behavior

| Proposal | Result |
| --- | --- |
| ST-02 | Settings, Sharing, SecurityRecovery, PersonalCenter, HelloSettings, DesktopUpdates, RecoveryRehearsal and PayloadUpgrade use the central bilingual task-page catalog. BackupCenter's catalog lives beside it. The catalog test checks key and interpolation-parameter parity. Other legacy components can migrate in later page-sized changes. |
| QW-06 | Copies use a single live toast based on the API's returned duration, conservatively subtracting request time. A new copy replaces the old timer; hovering does not pause the deadline. Lock invalidates old responses. Expiry removes the toast without claiming the OS clipboard was inspected or cleared. Sharing copy responses now include the same clear duration used by the backend. |
| ST-06 / ST-10 | Security has Overview, Password check, Automatic protection, Backups, Recovery, and Import and export task pages. Sharing has Limited shares, Family vaults, Connection, and Pending changes. Only the current task renders; pending shared drafts open in the family editor. Security remembers the selected task until lock. |
| QW-11 | More options follow Verification codes → Tags → Website matching rules → Custom fields → Attachments → History → Technical information. Conditional sections still depend on entry type and whether an entry is saved. |
| ST-11 | SettingsCard identifies immediate preferences and explicit-save forms. Protection settings and sharing connection drafts guard task/global navigation. Cancelling navigation keeps the input. Saving freezes protection fields; failures preserve the draft and do not report success. Initial settings-load failure shows Retry instead of editable defaults. |

## Preserved boundaries

Preview/apply routes, explicit confirmation, encrypted persistence and atomic writes
are unchanged. Discarding a draft does not submit it. Task unmount cancels active
import, sharing, format-upgrade and backup-restore previews. In-flight task results
cannot publish success after lock. Auto-lock still clears unsaved work.

The renderer controls only feedback for clipboard operations. It does not read
clipboard secrets, clear the clipboard itself, or redefine the existing backend's
concurrent-copy ordering. A slow old-session request does not queue a new-session
copy behind it.

## Local evidence

The new regression suite first reproduced the static countdown, silent loss of
protection settings, long security page and old editor order on the base source.
New tests cover both languages, leave/cancel/save, failed loads/saves, slow saves,
deadline expiry, multiple copy entry points and lock/session response races.

The existing sharing, migration, backup/restore, import/undo, format-upgrade and
password-health journeys use the new task navigation and retain their original
data-integrity assertions. The sharing API test uses the real authenticated routes
and isolated sharing fixture; only OS clipboard writing is substituted.

Local results on 2026-11-12:

- Backend: `.venv/Scripts/pytest.exe -q` — 612 passed (one existing Starlette/httpx deprecation warning).
- Full UI suite — 175 passed, with retries disabled. After the final current-page navigation guard and additional regression cases, the focused UI suite — 19 passed, with retries disabled.
- Production TypeScript/Vite build passed for both final regression and screenshot runs.
- Mutation check: removing the clipboard session-epoch guard through a temporary Vite alias made the stale-copy test fail; restoring production code passed it. The current-page navigation test also failed before its fix and passed afterward.
- Real screenshot journey — 1 passed; clipboard feedback changed from 45 to 43 seconds. The sharing-connection page had zero serious/critical axe findings. This is a scoped accessibility check, not a whole-app accessibility certification.
- UI artifact scans passed with zero unsafe files removed. Delivered PNGs were copied without modification and SHA-256 checked against those scanned outputs.

The local default port 1420 was occupied by an unrelated project. Ignored runtime
configs served this build on 19420 and mapped Chromium's 1420 transport to it,
preserving the expected origin and API authentication/CORS rules. CI configuration
was not changed. Reproduce without the local collision using:

```powershell
& ./scripts/run-ui-journeys.ps1 -TestFiles @('--retries=0')
& ./scripts/run-ui-journeys.ps1 -TestFiles @('uiux-finish.spec.ts', 'i18n-catalog.spec.ts', 'security-recovery-center.spec.ts', '--retries=0')
```

Screenshots and capture metadata: [evidence.json](uiux-finish-93/evidence.json).

| Visible change | Actual screenshot |
| --- | --- |
| Central bilingual text and immediate settings | [Chinese](uiux-finish-93/01-settings-zh.png), [English](uiux-finish-93/01-settings-en.png) |
| Copy countdown | [45 seconds](uiux-finish-93/02-copy-now.png), [43 seconds](uiux-finish-93/02-copy-countdown.png) |
| Task pages | [Recovery](uiux-finish-93/03-security-recovery.png), [Backups](uiux-finish-93/03-security-backups.png), [Family vaults](uiux-finish-93/03-sharing-family.png), [Connection](uiux-finish-93/03-sharing-connection.png) |
| Editor order | [Default window](uiux-finish-93/04-editor-default-window.png), [Taller window showing the first three sections](uiux-finish-93/04-editor-order.png) |
| Explicit save and leave protection | [Unsaved](uiux-finish-93/05-protection-unsaved.png), [Leave confirmation](uiux-finish-93/05-leave-confirm.png), [Saved](uiux-finish-93/05-protection-after-save.png) |
| Shared dark theme | [Settings](uiux-finish-93/05-settings-dark.png) |

Screenshots use the built renderer and a real sidecar with a newly generated vault;
they are not mockups or screenshots of the owner's daily installation. Native
Windows Hello, the packaged installer and real-user usability are outside this pass.

## Rollback

Revert the frontend and additive sharing response changes together, then rebuild.
No stored-vault migration or preference schema change is needed. Older renderers
ignore the additional `clears_in_seconds` response field.
