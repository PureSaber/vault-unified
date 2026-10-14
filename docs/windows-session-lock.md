# Windows lock and suspend

The Windows desktop registers its main native window for session notifications
and power broadcasts. `WM_WTSSESSION_CHANGE` lock/unlock and
`WM_POWERBROADCAST` suspend/resume go through a native worker, independently of
the renderer. Both the session-lock and suspend conditions must clear before a
new password unlock is allowed. Resume itself never creates a vault session.

Native notifications immediately request removal of visible entry/editor state.
The authenticated local API revokes all vault sessions and outstanding browser,
import and restore access. A short in-memory generation check rejects password
unlocks that started before a lock. The API also discards private responses that
were still in flight when the Windows session changed. These checks do not add
a data migration or persisted lock/hash file.

The native callback waits at most 1.5 seconds for acknowledgement, within
Windows' approximately two-second suspend allowance. If the sidecar cannot
acknowledge, the desktop terminates its owned sidecar and exits. Restart and use
the master password in that case. Existing atomic writes protect saved data.

Unsaved drafts are cleared without a discard confirmation on a system lock.
Manual Lock/Quit still uses the existing draft confirmation. Browser devices
remain authorized but must acquire new access after the vault is unlocked.

## Evidence and acceptance

Four backend tests cover all-session/browser revocation, desktop authentication,
in-flight read rejection and unlock/lock races. Existing device-unlock and browser
pairing regressions passed. Renderer handoff clears a dirty draft without a
dialog. The isolated native executable journey posts real Win32 session/power
notifications to its own generated test window and checks API denial, overlapping
suspend/lock state, draft removal and explicit re-unlock. This does not lock or
sleep the operator's computer.

Final installed acceptance: edit a generated draft, press Win+L and return;
confirm the vault is locked and the draft gone. Repeat with Sleep while the app
is in the tray, then confirm browser filling needs an unlocked vault. Windows
Hello biometric acceptance is a separate item.

References: [session notifications](https://learn.microsoft.com/en-us/windows/win32/termserv/wm-wtssession-change),
[suspend notification and time allowance](https://learn.microsoft.com/en-us/windows/win32/power/pbt-apmsuspend).

Rollback: revert the increment. The vault format and saved data are unchanged;
manual and idle locking return to their previous behavior.
