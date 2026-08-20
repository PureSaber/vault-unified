# Build vault-api-sidecar.exe with PyInstaller for Tauri externalBin.
$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location -LiteralPath $RepoRoot

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$VenvPip = Join-Path $RepoRoot ".venv\Scripts\pip.exe"

if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Host "Creating .venv ..."
    python -m venv .venv
}

Write-Host "Installing API deps + PyInstaller ..."
& $VenvPip install -e ".[api]" pyinstaller | Out-Host

$OutDir = Join-Path $RepoRoot "apps\desktop\src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

# Unlock previous build artifacts only when the process executable is one of
# this checkout's build outputs. Never stop an installed or unrelated sidecar.
$OutDirFull = [System.IO.Path]::GetFullPath($OutDir).TrimEnd('\')
Get-Process -Name "vault-api-sidecar*" -ErrorAction SilentlyContinue |
    ForEach-Object {
        $ProcessPath = $null
        try { $ProcessPath = $_.Path } catch { }
        if ($ProcessPath) {
            $ProcessDir = [System.IO.Path]::GetDirectoryName(
                [System.IO.Path]::GetFullPath($ProcessPath)
            ).TrimEnd('\')
            if ($ProcessDir -eq $OutDirFull) {
                Write-Host "Stopping checkout sidecar $($_.ProcessName) (PID $($_.Id)) ..."
                Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
            } else {
                Write-Host "Leaving unrelated sidecar running: $ProcessPath"
            }
        }
    }
Start-Sleep -Seconds 1
Get-ChildItem -LiteralPath $OutDir -Filter "vault-api-sidecar*.exe" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

$Entry = Join-Path $RepoRoot "scripts\vault_api_sidecar.py"
$Collect = @(
    "vault_unified",
    "uvicorn",
    "fastapi",
    "pydantic",
    "cryptography",
    "keyring",
    "dotenv",
    "click",
    "rich"
)

$PyInstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name", "vault-api-sidecar",
    "--distpath", $OutDir,
    "--workpath", (Join-Path $RepoRoot "build\pyinstaller"),
    "--specpath", (Join-Path $RepoRoot "build\pyinstaller")
)
foreach ($mod in $Collect) {
    $PyInstallerArgs += @("--collect-submodules", $mod)
}
$PyInstallerArgs += $Entry

Write-Host "Running PyInstaller ..."
& $VenvPython -m PyInstaller @PyInstallerArgs
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$Plain = Join-Path $OutDir "vault-api-sidecar.exe"
if (-not (Test-Path -LiteralPath $Plain)) {
    throw "Expected sidecar at $Plain"
}

$Triple = "x86_64-pc-windows-msvc"
$Tripled = Join-Path $OutDir "vault-api-sidecar-$Triple.exe"
Copy-Item -LiteralPath $Plain -Destination $Tripled -Force

Write-Host "Sidecar ready:"
Write-Host "  $Plain"
Write-Host "  $Tripled"
