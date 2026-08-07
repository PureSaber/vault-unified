# Configure Proton Pass + Bitwarden for Vault Unified (writes .env locally — never commit)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Read-Secret([string]$Prompt) {
    $secure = Read-Host $Prompt -AsSecureString
    [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    )
}

Write-Host ""
Write-Host "Vault Unified — External source setup" -ForegroundColor Cyan
Write-Host "Credentials are saved to .env on this PC only (gitignored)." -ForegroundColor DarkGray
Write-Host ""

# --- Proton Pass ---
Write-Host "=== Proton Pass ===" -ForegroundColor Yellow
Write-Host "Get a Personal Access Token: Proton web -> Pass -> Settings -> Security -> Personal access tokens"
$protonToken = Read-Secret "Proton PAT (pst_..., Enter to skip)"
$protonShare = ""
$protonVault = "Personal"
if ($protonToken) {
    $protonShare = Read-Host "Proton share ID (optional, Enter to skip)"
    $vaultInput = Read-Host "Proton vault name [Personal]"
    if ($vaultInput) { $protonVault = $vaultInput }
}

Write-Host ""
Write-Host "=== Bitwarden ===" -ForegroundColor Yellow
Write-Host "Get API key: https://vault.bitwarden.com/#/settings/security/security-keys"
$bwClientId = Read-Host "BW_CLIENTID (user.xxx, Enter to skip)"
$bwSecret = ""
$bwPassword = ""
$bwServer = "https://vault.bitwarden.com"
if ($bwClientId) {
    $bwSecret = Read-Secret "BW_CLIENTSECRET"
    $bwPassword = Read-Secret "Bitwarden master password"
    $serverInput = Read-Host "BW_SERVER [$bwServer]"
    if ($serverInput) { $bwServer = $serverInput }
}

Write-Host ""
Write-Host "=== KeePassXC ===" -ForegroundColor Yellow
Write-Host "Or run: powershell -File scripts\setup-keepassxc.ps1"
$kpxDb = Read-Host "KEEPASSXC_DATABASE path (.kdbx, Enter to skip)"
$kpxPass = ""
$kpxKeyFile = ""
$kpxGroup = ""
if ($kpxDb) {
    $kpxPass = Read-Secret "KEEPASSXC_PASSWORD (database master password)"
    $kpxKeyFile = Read-Host "KEEPASSXC_KEY_FILE (optional)"
    $kpxGroup = Read-Host "KEEPASSXC_GROUP (optional)"
}

Write-Host ""
Write-Host "=== gopass ===" -ForegroundColor Yellow
Write-Host "Or run: powershell -File scripts\setup-gopass.ps1"
$gpStore = Read-Host "GOPASS_STORE (optional, Enter for default)"
$gpMount = Read-Host "GOPASS_MOUNT (optional)"
$gpPrefix = Read-Host "GOPASS_PATH_PREFIX [vault]"
if (-not $gpPrefix) { $gpPrefix = "vault" }

$lines = @(
    "# Vault Unified — local credentials (DO NOT commit)",
    "",
    "# Proton Pass CLI",
    "PROTON_PASS_PERSONAL_ACCESS_TOKEN=$protonToken",
    "PROTON_PASS_SHARE_ID=$protonShare",
    "PROTON_PASS_VAULT_NAME=$protonVault",
    "",
    "# Bitwarden CLI",
    "BW_CLIENTID=$bwClientId",
    "BW_CLIENTSECRET=$bwSecret",
    "BW_PASSWORD=$bwPassword",
    "BW_SERVER=$bwServer",
    "",
    "# KeePassXC CLI",
    "KEEPASSXC_DATABASE=$kpxDb",
    "KEEPASSXC_PASSWORD=$kpxPass",
    "KEEPASSXC_KEY_FILE=$kpxKeyFile",
    "KEEPASSXC_GROUP=$kpxGroup",
    "",
    "# gopass CLI",
    "GOPASS_STORE=$gpStore",
    "GOPASS_MOUNT=$gpMount",
    "GOPASS_PATH_PREFIX=$gpPrefix",
    "",
    "# API server (desktop app sidecar)",
    "VAULT_API_HOST=127.0.0.1",
    "VAULT_API_PORT=8765"
)

$lines | Set-Content -Path ".env" -Encoding UTF8
Write-Host ""
Write-Host "Wrote .env" -ForegroundColor Green

# Verify CLIs
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')

Write-Host ""
Write-Host "Checking integrations..." -ForegroundColor Cyan
& .\.venv\Scripts\vault.exe status 2>&1

if ($protonToken) {
    $env:PROTON_PASS_PERSONAL_ACCESS_TOKEN = $protonToken
    if ($protonShare) { $env:PROTON_PASS_SHARE_ID = $protonShare }
    if ($protonVault) { $env:PROTON_PASS_VAULT_NAME = $protonVault }
    $pp = & pass-cli item list --output json 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Proton Pass: connected" -ForegroundColor Green
    } else {
        Write-Host "Proton Pass: token set but API check failed — verify PAT permissions" -ForegroundColor Yellow
    }
}

if ($bwClientId -and $bwSecret -and $bwPassword) {
    $env:BW_CLIENTID = $bwClientId
    $env:BW_CLIENTSECRET = $bwSecret
    $env:BW_PASSWORD = $bwPassword
    $env:BW_SERVER = $bwServer
    $unlock = & bw unlock --passwordenv BW_PASSWORD --raw 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Bitwarden: connected" -ForegroundColor Green
    } else {
        Write-Host "Bitwarden: credentials saved but unlock failed — check API key / password" -ForegroundColor Yellow
    }
}

if ($kpxDb -and $kpxPass) {
    $env:KEEPASSXC_DATABASE = $kpxDb
    $env:KEEPASSXC_PASSWORD = $kpxPass
    $test = $kpxPass | keepassxc-cli ls $kpxDb 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "KeePassXC: connected" -ForegroundColor Green
    } else {
        Write-Host "KeePassXC: saved but unlock failed — check path/password" -ForegroundColor Yellow
    }
}

if (Get-Command gopass -ErrorAction SilentlyContinue) {
    $gp = gopass ls 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Host "gopass: store available" -ForegroundColor Green
    } else {
        Write-Host "gopass: run scripts\setup-gopass.ps1 to initialize" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Done. Run: .\vault.cmd sync   or   .\launch-desktop.ps1" -ForegroundColor Green
