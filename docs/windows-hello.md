# Windows Hello quick unlock

After unlocking with the master password, open **Settings → Windows Hello** and
choose **Enable Windows Hello for this run / 为本次运行启用 Windows Hello**. Complete
the Windows fingerprint, face or PIN prompt. Later locks show an **Unlock with
Windows Hello / 使用 Windows Hello 解锁** button. Cancelling leaves the vault locked;
the master-password option stays available. Disable clears this run's material.

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
master fallback, with accessibility and generated-artifact scanning. These
renderer tests substitute native identity verification.

The isolated Windows executable checks real WinRT availability without opening
a biometric prompt, capability isolation, the native/API clear operation, and
session/power lock behavior. Real owner identity verification is reserved for
installed final acceptance:

1. Restart, confirm Hello unlock is absent, unlock with the master password.
2. Enable for this run; cancel the prompt and verify it stays disabled. Retry
   with Windows verification, manually lock, then unlock with Hello.
3. Cancel an unlock; confirm the password fallback works. Disable and lock;
   confirm Hello is unavailable.
4. Enable again, lock Windows or sleep during verification, then return. Confirm
   the vault remains locked and requires a fresh explicit unlock.
5. Quit and restart; repeat the master-first requirement.

Rollback: revert the increment; no vault migration is needed. The OS-managed
application signing credential contains no vault password. Old process-only
material disappears on exit.
