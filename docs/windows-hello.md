# Windows Hello quick unlock

After you type the master password (unlock or vault creation), Vault Unified
offers quick unlock when Windows Hello is supported and not yet enabled for this
run: **Unlock with Windows Hello? / 使用 Windows Hello 快速解锁？** It explains that
later locks in this run can be unlocked with the fingerprint, face or Windows PIN
set up on the computer, and that the master password is still required first
after a restart.

- **Enable / 启用** runs the same enrollment as Settings and shows the Windows
  prompt. A cancelled or failed prompt keeps the offer open with the reason.
- **Not now / 暂不** (or Escape) hides the offer for the rest of this run
  (`sessionStorage`, cleared when the app restarts).
- **Don't ask again / 不再询问** stops the offer until it is turned back on in
  **Settings → Windows Hello → After I unlock with the master password, offer to
  turn on Windows Hello for that run / 使用主密码解锁后，询问是否为本次运行启用
  Windows Hello** (`localStorage`, a non-secret preference).

No offer appears after a saved-password or Hello unlock, including pressing
Enter on an empty password field to use the saved password (such sessions cannot
enroll), when Hello is unsupported, or while quick search, a passkey approval,
an unsaved-change prompt or the idle-lock warning is shown; it waits for those.
You can also enable it manually in **Settings → Windows Hello** with **Enable
Windows Hello for this run / 为本次运行启用 Windows Hello**. Once enabled, later
locks show **Unlock with Windows Hello / 使用 Windows Hello 解锁** as the primary
action; the master-password field stays available and Enter still submits it.
Cancelling leaves the vault locked. Disable clears this run's material.

Each application launch starts without Hello quick unlock. Use the master
password and explicitly enable it again. Device-only and Hello unlock sessions
cannot enroll a new grant. If Windows Hello is unavailable, configure it in
Windows Settings → Accounts → Sign-in options, or keep using the master password.

![Generated Hello settings](screenshots/windows-hello-zh.png)

## Key operation and boundaries

The native process uses Windows `KeyCredentialManager` to create/open an
application-specific credential and `RequestSignAsync` for user verification.
SHA-256 of the signature over a fresh per-run challenge wraps the master
credential with AES-256-GCM. The native process retains only the challenge and
grant identifier; the API retains only ciphertext, nonce and vault path. The
Windows private key stays with Windows. Temporary native signature/key buffers
are zeroized. Python cannot guarantee erasure of previously allocated strings.

No quick-unlock credential is written to the vault, settings, backup or sync.
The sidecar startup pipe supplies a separate native capability that is excluded
from renderer serialization. Hello and system-state endpoints require it as well
as the sidecar bootstrap. CORS does not allow the native header. Browser access
cannot call these endpoints. Authentication material is absent from errors/logs.

System lock/suspend invalidates ongoing native verification before revoking API
sessions. Disable invalidates pending requests and clears the encrypted cache;
late successful sessions are revoked. Cache replacement during decrypt and late
session registration after a system lock are rejected. A changed master password
invalidates the prior cache on use. No background verification starts by itself.

References: [Microsoft KeyCredentialManager](https://learn.microsoft.com/en-us/uwp/api/windows.security.credentials.keycredentialmanager),
[RequestSignAsync](https://learn.microsoft.com/en-us/uwp/api/windows.security.credentials.keycredential.requestsignasync).
The signature-derived wrapping approach is also used by
[KeePassXC's Windows quick unlock](https://github.com/keepassxreboot/keepassxc/blob/develop/src/quickunlock/WindowsHello.cpp).

## Verification and final acceptance

Backend tests cover encrypted process-only storage, master-first enrollment,
native-only authorization, redacted validation, invalid key, disable/decrypt race
and system lock. Renderer tests cover bilingual enrollment/cancel/disable and
master fallback, with accessibility and generated-artifact scanning.
`windows-hello-prompt.spec.ts` covers the post-unlock offer in both languages:
accept, Not now for the run, a new run asking again, Don't ask again and its
Settings re-enable (which also clears a Not now for the run), Escape, the focus
trap, locking while the offer is open, a cancelled prompt with password
fallback, Enter submitting the master password while Hello is the primary
action, and no offer when unsupported or after a saved-password, empty-field or
Hello unlock. These renderer
tests substitute native identity verification.

The isolated Windows executable checks real WinRT availability without opening
a biometric prompt, capability isolation, the native/API clear operation, and
session/power lock behavior. Real owner identity verification is reserved for
installed final acceptance:

1. Restart, confirm Hello unlock is absent, unlock with the master password.
2. In the offer that appears, choose Enable; cancel the Windows prompt and verify
   the offer explains it and Hello stays disabled. Choose Enable again, complete
   Windows verification, manually lock, then unlock with Hello. Restart, choose
   Not now, lock and unlock with the master password: no second offer this run.
3. Cancel an unlock; confirm the password fallback works. Disable and lock;
   confirm Hello is unavailable.
4. Enable again, lock Windows or sleep during verification, then return. Confirm
   the vault remains locked and requires a fresh explicit unlock.
5. Quit and restart; repeat the master-first requirement. Choose Don't ask
   again, restart, unlock with the master password and confirm no offer; turn
   the offer back on in Settings.

Rollback: revert the increment; no vault migration is needed. The OS-managed
application signing credential contains no vault password. Old process-only
material disappears on exit.
