# One-click desktop dev: API + Tauri
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path "$root\pyproject.toml")) { $root = "C:\develop\token&password" }
Set-Location $root

Write-Host "==> Installing Python API deps..."
.\.venv\Scripts\pip install -e ".[dev]" -q

Write-Host "==> Installing desktop npm deps..."
Set-Location "$root\apps\desktop"
if (-not (Test-Path node_modules)) { npm install }

Write-Host "==> Starting desktop app..."
npm run tauri dev
