# Build API sidecar + Tauri desktop release (NSIS/MSI).
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location -LiteralPath $RepoRoot

Write-Host "=== 1/2 API sidecar ==="
& (Join-Path $PSScriptRoot "build-api-sidecar.ps1")

Write-Host "=== 2/2 Tauri build ==="
Set-Location -LiteralPath (Join-Path $RepoRoot "apps\desktop")
npm ci
if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }

npm run tauri build
$tauriExit = $LASTEXITCODE
Set-Location -LiteralPath $RepoRoot
if ($tauriExit -ne 0) { throw "tauri build failed" }

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
