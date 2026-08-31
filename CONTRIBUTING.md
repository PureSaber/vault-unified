# Contributing to Vault Unified

Thank you for helping improve Vault Unified. Keep changes small, reviewable, independently reversible, and inside the current feature-freeze contract in [`docs/feature-freeze-v1.3.md`](docs/feature-freeze-v1.3.md).

## Safety first

- Use only newly generated fake credentials and isolated data directories.
- Never use or attach a real vault, master password, token, TOTP key, recovery code, attachment, plaintext export, log, screenshot, or trace.
- Do not write bearer, browser-pairing, or bootstrap tokens to persistent browser storage.
- Do not weaken encryption, authentication, preview/confirmation, atomic-write, device-storage, or auto-lock boundaries to make a test pass.
- Report exploitable findings privately according to [`SECURITY.md`](SECURITY.md).

## Windows development setup

The supported desktop build environment is Windows. Install:

- Python 3.12 (the package supports Python 3.10 or newer);
- Node.js 20 and npm;
- the stable Rust toolchain with the MSVC target;
- WebView2 and the Windows build prerequisites required by Tauri.

Create an isolated Python environment and install the project:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
```

Install desktop dependencies:

```powershell
Set-Location apps\desktop
npm ci
Set-Location ..\..
```

Normal contributors do not need to configure an external password manager. Tests use generated data and an isolated API.

## Required checks

Run the checks relevant to the change, plus the full suites before requesting merge:

```powershell
.\.venv\Scripts\pytest -q
.\.venv\Scripts\python -m pip install pip==26.2.1 pip-audit==2.10.1
.\.venv\Scripts\python -m pip_audit --local --skip-editable --progress-spinner off
.\.venv\Scripts\python scripts\scan_repository_secrets.py --repo-root .

Set-Location apps\desktop
npm run lint
npm run build
npm run test:ui:install
npm run test:ui
Set-Location ..\..

cargo test --manifest-path apps\desktop\src-tauri\Cargo.toml --lib
cargo audit --file apps\desktop\src-tauri\Cargo.lock
```

CI downloads a pinned, hash-verified `cargo-audit` executable for RustSec; use that CI implementation if a local `cargo audit` installation is unavailable. Release validation uses:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build-desktop-release.ps1
pwsh -NoProfile -File scripts\validate-desktop-release.ps1
```

The release commands build installers and are slower than pull-request checks. They must run with generated data only.

## Pull requests

Create a branch and pull request; never push directly to `main` or force-push it. One pull request should deliver one coherent outcome. Complete every section of the pull-request template, including tests, security/data-integrity scope, remaining risks, and rollback instructions.

- UI changes require generated-data screenshots or recordings where useful, a Playwright regression, an accessibility check, and a successful artifact secret scan.
- Security-sensitive changes require explicit trust-boundary analysis and negative tests. Do not publish an exploitable detail in a public PR before coordinating privately.
- Data-format changes must be additive, optional, namespaced, defaulted, backward-compatible, and tested against old data. Include a lossless rollback plan.
- Bulk, delete, overwrite, import, sync, and restore changes need preview, explicit confirmation, state/digest binding, stale-preview rejection, idempotency tests, and cancellation tests.
- A UI mock does not prove the packaged Tauri lifecycle. State which layer was actually tested.
- Automated journeys do not replace research with real novice users.

Wait for required CI checks and review before merging. Update the v1.3 tracking issue with completed evidence and remaining dependencies.

## Documentation and language

Write default user-facing text for people who do not know the implementation. Put internal terms behind contextual “Technical details” or “Advanced options” disclosures. Keep Chinese and English behavior aligned when changing the desktop UI.
