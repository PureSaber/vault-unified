# Vault Unified integration setup launcher
#
# Production credentials are managed in the desktop Settings page and stored in
# Windows Credential Manager. This script intentionally does not collect or
# write passwords/tokens to .env. Environment variables remain supported only
# as an explicit development/automation fallback.
#
# Desktop sidecar security contract: VAULT_API_PORT=0 (OS-assigned random port).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "" 
Write-Host "Vault Unified — secure integration setup" -ForegroundColor Cyan
Write-Host "Credentials are no longer written to .env." -ForegroundColor Green
Write-Host "Open Settings -> External password-manager connections to save and test each source." -ForegroundColor Yellow
Write-Host "Secrets are stored in Windows Credential Manager; paths and server names use LocalAppData config." -ForegroundColor DarkGray
Write-Host ""

if (-not (Test-Path ".\launch-desktop.ps1")) {
    throw "launch-desktop.ps1 was not found in $PSScriptRoot"
}

& powershell -ExecutionPolicy Bypass -File ".\launch-desktop.ps1"
