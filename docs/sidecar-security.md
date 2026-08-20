# Desktop sidecar security boundary

Vault Unified's desktop renderer must never trust a process merely because it is listening on a localhost port.

## Runtime design

For every desktop launch:

1. The Tauri parent starts a new API sidecar. It never reuses an already-running process.
2. The sidecar binds `127.0.0.1` on an OS-assigned random port (`port=0`) before announcing readiness.
3. The sidecar generates a fresh high-entropy bootstrap secret and instance ID.
4. Readiness is sent only through the child stdout pipe as a single `VAULT_API_READY ...` record.
5. The parent verifies `/api/health` with both the bootstrap secret and the expected instance ID.
6. The renderer receives the runtime endpoint through a Tauri command and includes `X-Vault-Bootstrap` on every API request.
7. Bearer session tokens remain in renderer memory and are discarded on reload, lock, or exit.
8. On Windows, Tauri starts the sidecar suspended, assigns it to a kill-on-close Job Object, and only then resumes it. Closing or crashing the parent therefore terminates the PyInstaller bootloader and worker process tree.

This prevents an unrelated local process from occupying a predictable port and impersonating the vault API to capture the master password or a bearer token.

## Security invariants

- Normal desktop mode has no fixed API port.
- Normal desktop mode has no persistent bootstrap secret.
- No API request, including health checks and unlock, succeeds without the per-process bootstrap secret.
- CORS preflight may proceed, but the resulting request still requires the secret.
- A sidecar handshake that names a non-loopback host, an empty instance ID, a zero port, or a short secret is rejected.
- A health response from a different instance ID is rejected.
- Failure to start or authenticate the owned sidecar prevents the desktop application from opening.

## Manual API debugging

The standalone `vault-api` command binds a random loopback port by default and prints one readiness record containing the temporary endpoint and bootstrap secret. Use it only in a trusted terminal for debugging. Normal users should launch the Tauri application through `launch-desktop.ps1` or the packaged executable.

For browser-only Vite development, both variables must be supplied explicitly for the same manually launched API instance:

```text
VITE_API_URL=http://127.0.0.1:<random-port>/api
VITE_API_BOOTSTRAP_SECRET=<temporary-secret-from-ready-record>
```

There is deliberately no fallback to `127.0.0.1:8765`.
