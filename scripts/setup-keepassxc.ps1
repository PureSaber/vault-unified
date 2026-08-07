# KeePassXC setup for Vault Unified (Windows)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

Write-Host ""
Write-Host "Vault Unified — KeePassXC setup" -ForegroundColor Cyan

function Read-Secret([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    )
}

if (-not (Get-Command keepassxc-cli -ErrorAction SilentlyContinue)) {
    Write-Host "Installing KeePassXC via winget..." -ForegroundColor Yellow
    winget install KeePassXCTeam.KeePassXC --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
}

$defaultDir = Join-Path $env:USERPROFILE "OneDrive\Passwords"
if (-not (Test-Path $defaultDir)) {
    $defaultDir = Join-Path $env:USERPROFILE "Documents\Passwords"
}
New-Item -ItemType Directory -Force -Path $defaultDir | Out-Null
$defaultDb = Join-Path $defaultDir "vault-unified.kdbx"

Write-Host ""
Write-Host "1) Use existing .kdbx file"
Write-Host "2) Create new database at default path: $defaultDb"
$choice = Read-Host "Choice [1/2] (default 2)"
if ($choice -eq "1") {
    $dbPath = Read-Host "Full path to .kdbx file"
} else {
    $dbPath = $defaultDb
    if (-not (Test-Path $dbPath)) {
        $dbPass = Read-Secret "Master password for new KeePassXC database"
        $dbPass | keepassxc-cli db-create --set-password-key "$dbPath"
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Failed to create database. Try creating it in KeePassXC GUI." -ForegroundColor Red
            exit 1
        }
        Write-Host "Created: $dbPath" -ForegroundColor Green
    } else {
        Write-Host "Database already exists: $dbPath" -ForegroundColor Yellow
    }
}

$dbPass = Read-Secret "KeePassXC database master password (for .env)"
$group = Read-Host "Default group prefix (optional, e.g. VaultUnified)"
$keyFile = Read-Host "Key file path (optional, Enter to skip)"

# Merge into .env
$envPath = Join-Path $PSScriptRoot "..\.env"
$lines = @()
if (Test-Path $envPath) {
    $lines = Get-Content $envPath
    $lines = $lines | Where-Object {
        $_ -notmatch '^(KEEPASSXC_DATABASE|KEEPASSXC_PASSWORD|KEEPASSXC_KEY_FILE|KEEPASSXC_GROUP)='
    }
}
$lines += ""
$lines += "# KeePassXC CLI"
$lines += "KEEPASSXC_DATABASE=$dbPath"
$lines += "KEEPASSXC_PASSWORD=$dbPass"
$lines += "KEEPASSXC_KEY_FILE=$keyFile"
$lines += "KEEPASSXC_GROUP=$group"
$lines | Set-Content -Path $envPath -Encoding UTF8

Write-Host ""
Write-Host "Wrote KeePassXC settings to .env" -ForegroundColor Green
Write-Host "Verify: .\vault.cmd status" -ForegroundColor Cyan
