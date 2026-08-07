# Launch Vault Unified desktop (API + Tauri)
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

Write-Host "==> Installing Python dependencies..."
.\.venv\Scripts\pip install -e ".[api]" -q

$apiPort = 8765
$healthUrl = "http://127.0.0.1:$apiPort/api/auth/check-keyring"

# Start API if not already running
$apiRunning = $false
try {
    $null = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
    $apiRunning = $true
    Write-Host "==> API already running on port $apiPort"
} catch {
    Write-Host "==> Starting vault API on port $apiPort..."
    Start-Process `
        -FilePath ".\.venv\Scripts\python.exe" `
        -ArgumentList "-m", "vault_unified.api.app" `
        -WorkingDirectory $root `
        -WindowStyle Hidden

    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Milliseconds 500
        try {
            $null = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
            $apiRunning = $true
            break
        } catch { }
    }
}

if (-not $apiRunning) {
    Write-Host "[ERROR] Could not start vault API. Run manually: vault-api" -ForegroundColor Red
    exit 1
}

Write-Host "==> API ready. Launching desktop app..."
Set-Location "$root\apps\desktop"

$exe = ".\src-tauri\target\release\vault-unified-desktop.exe"
if (Test-Path $exe) {
    & $exe
} elseif (Test-Path ".\src-tauri\target\release\Vault Unified.exe") {
    & ".\src-tauri\target\release\Vault Unified.exe"
} else {
  if (-not (Test-Path node_modules)) { npm install }
  npm run tauri dev
}
