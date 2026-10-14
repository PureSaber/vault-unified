# Build API sidecar + Tauri desktop release (NSIS/MSI).
param([switch]$SkipNpmInstall)
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $RepoRoot

# A signed release must never silently fall back to an unsigned installer.
if (-not $env:TAURI_SIGNING_PRIVATE_KEY) {
    $LocalSigningKey = Join-Path $RepoRoot "secrets\updater\vault-unified-release.key"
    if (-not (Test-Path -LiteralPath $LocalSigningKey -PathType Leaf)) {
        throw "Set TAURI_SIGNING_PRIVATE_KEY to the release key path before building."
    }
    $env:TAURI_SIGNING_PRIVATE_KEY = $LocalSigningKey
}

Write-Host "=== 1/3 API sidecar ==="
& (Join-Path $PSScriptRoot "build-api-sidecar.ps1")

Write-Host "=== 2/3 Browser extension release ZIP ==="
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
& $VenvPython (Join-Path $PSScriptRoot "build_browser_extension.py") --repo-root $RepoRoot --output-dir $RepoRoot
if ($LASTEXITCODE -ne 0) { throw "browser extension build failed" }

Write-Host "=== 3/3 Tauri build ==="
Set-Location -LiteralPath (Join-Path $RepoRoot "apps\desktop")
if (-not $SkipNpmInstall) {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
}

npm run tauri build
$tauriExit = $LASTEXITCODE
Set-Location -LiteralPath $RepoRoot
if ($tauriExit -ne 0) { throw "tauri build failed" }

& $VenvPython (Join-Path $PSScriptRoot "build_release_assets.py") --repo-root $RepoRoot --output-dir $RepoRoot
if ($LASTEXITCODE -ne 0) { throw "Release kit assembly failed" }
$env:VAULT_VERIFY_UPDATE_DIR = $RepoRoot
try {
    cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --test updater_transport verify_release_artifacts_when_requested -- --exact
    if ($LASTEXITCODE -ne 0) { throw "Actual release signature verification failed" }
} finally {
    Remove-Item Env:VAULT_VERIFY_UPDATE_DIR -ErrorAction SilentlyContinue
}

$Bundle = Join-Path $RepoRoot "apps\desktop\src-tauri\target\release\bundle"
$Nsis = Join-Path $Bundle "nsis"
$Msi = Join-Path $Bundle "msi"

Write-Host ""
Write-Host "Desktop release build finished."
Write-Host "Look for installers under:"
if (Test-Path -LiteralPath $Nsis) {
    Get-ChildItem -LiteralPath $Nsis -Filter "*.exe" | ForEach-Object { Write-Host "  NSIS: $($_.FullName)" }
} else {
    Write-Host "  NSIS dir (if enabled): $Nsis"
}
if (Test-Path -LiteralPath $Msi) {
    Get-ChildItem -LiteralPath $Msi -Filter "*.msi" | ForEach-Object { Write-Host "  MSI:  $($_.FullName)" }
} else {
    Write-Host "  MSI dir (if enabled): $Msi"
}
Write-Host "  Bundle root: $Bundle"
$Version = [string](Get-Content -LiteralPath (Join-Path $RepoRoot "apps\desktop\package.json") -Raw | ConvertFrom-Json).version
$Extension = Join-Path $RepoRoot "Vault-Unified-Browser-Extension-v$Version.zip"
Write-Host "  Browser extension: $Extension"
