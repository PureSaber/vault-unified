# Sidecar binaries (gitignored)

Run from the repo root before `tauri build` or use the release script:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-api-sidecar.ps1
```

That produces:

- `vault-api-sidecar.exe` — used by `lib.rs` when present next to the app / in this folder
- `vault-api-sidecar-x86_64-pc-windows-msvc.exe` — required by Tauri `bundle.externalBin`

Full desktop release (sidecar + installer):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-desktop-release.ps1
```
