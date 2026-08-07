# gopass bootstrap for Vault Unified (Windows)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host ""
Write-Host "Vault Unified — gopass setup" -ForegroundColor Cyan

function Ensure-WingetPackage([string]$Id) {
    if (-not (winget list --id $Id 2>$null | Select-String $Id)) {
        Write-Host "Installing $Id ..." -ForegroundColor Yellow
        winget install $Id --accept-package-agreements --accept-source-agreements
    }
}

Ensure-WingetPackage "Git.Git"
Ensure-WingetPackage "GnuPG.Gpg4win"
Ensure-WingetPackage "gopass.gopass"
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

Write-Host ""
Write-Host "Checking GPG keys..." -ForegroundColor Cyan
$keys = gpg --list-secret-keys --keyid-format LONG 2>&1
if ($LASTEXITCODE -ne 0 -or -not ($keys -match "sec")) {
    Write-Host "No GPG secret key found." -ForegroundColor Yellow
    Write-Host "Create one with Kleopatra (Gpg4win) or run: gpg --full-generate-key"
    Write-Host "Then re-run this script."
    exit 1
}

if (-not (gopass ls 2>$null)) {
    Write-Host "Initializing gopass store (gopass setup)..." -ForegroundColor Yellow
    Write-Host "Follow the interactive prompts to select your GPG key."
    gopass setup
}

$prefix = Read-Host "GOPASS_PATH_PREFIX for new entries [vault]"
if (-not $prefix) { $prefix = "vault" }
$mount = Read-Host "GOPASS_MOUNT (optional sub-store, Enter to skip)"

$envPath = Join-Path $PSScriptRoot "..\.env"
$lines = @()
if (Test-Path $envPath) {
    $lines = Get-Content $envPath
    $lines = $lines | Where-Object {
        $_ -notmatch '^(GOPASS_STORE|GOPASS_MOUNT|GOPASS_PATH_PREFIX)='
    }
}
$lines += ""
$lines += "# gopass CLI"
$lines += "GOPASS_STORE="
$lines += "GOPASS_MOUNT=$mount"
$lines += "GOPASS_PATH_PREFIX=$prefix"
$lines | Set-Content -Path $envPath -Encoding UTF8

Write-Host ""
Write-Host "Creating test entry vault-unified-setup ..." -ForegroundColor Cyan
"setup-ok" | gopass insert -f "$prefix/vault-unified-setup" 2>$null

Write-Host "Wrote gopass settings to .env" -ForegroundColor Green
Write-Host "Verify: gopass ls && .\vault.cmd status" -ForegroundColor Cyan
