# One-click setup for Vault Unified (Windows)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> Vault Unified setup" -ForegroundColor Cyan

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python not found. Install Python 3.10+ first." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".venv")) {
    Write-Host "==> Creating virtual environment..."
    python -m venv .venv
}

Write-Host "==> Installing dependencies..."
.\.venv\Scripts\pip install -e . -q

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "==> Created .env (edit for Proton Pass / Bitwarden)" -ForegroundColor Yellow
}

Write-Host "==> Running first-time wizard..."
.\.venv\Scripts\vault setup

Write-Host ""
Write-Host "Done! Next time just run:" -ForegroundColor Green
Write-Host "  .\vault.cmd" -ForegroundColor White
Write-Host "  or double-click vault.cmd" -ForegroundColor White
