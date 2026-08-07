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

Write-Host ""
Write-Host "Done. Run: .\vault.cmd sync   or   .\launch-desktop.ps1" -ForegroundColor Green
