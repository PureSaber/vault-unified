# Launch Vault Unified desktop.
# The Tauri process exclusively owns the API sidecar lifecycle, random loopback
# port, and per-process bootstrap secret. Do not pre-start or reuse a fixed API.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$releaseCandidates = @(
    "$root\apps\desktop\src-tauri\target\release\vault-unified-desktop.exe",
    "$root\apps\desktop\src-tauri\target\release\Vault Unified.exe"
)
foreach ($candidate in $releaseCandidates) {
    if (Test-Path -LiteralPath $candidate) {
        Write-Host "==> Launching packaged Vault Unified..."
        & $candidate
        exit $LASTEXITCODE
    }
}

Write-Host "==> Preparing development dependencies..."
if (-not (Test-Path -LiteralPath "$root\.venv\Scripts\python.exe")) {
    python -m venv "$root\.venv"
}
& "$root\.venv\Scripts\pip.exe" install -e ".[api]" -q

Set-Location "$root\apps\desktop"
if (-not (Test-Path -LiteralPath "node_modules")) {
    npm install
}

Write-Host "==> Launching Tauri; it will start an authenticated random-port sidecar..."
npm run tauri dev
