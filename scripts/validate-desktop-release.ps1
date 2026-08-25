param(
    [string]$Version = "",
    [string]$SourceSha = "",
    [string]$RepoRoot = $PSScriptRoot
)

$ErrorActionPreference = "Stop"
if (-not $RepoRoot) { $RepoRoot = $env:GITHUB_WORKSPACE }
$RepoRoot = (Resolve-Path -LiteralPath (Join-Path $RepoRoot "..") -ErrorAction SilentlyContinue).Path ?? (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "pyproject.toml"))) {
    $RepoRoot = (Resolve-Path -LiteralPath $env:GITHUB_WORKSPACE).Path
}
Set-Location -LiteralPath $RepoRoot

if (-not $Version) {
    $Version = [string](Get-Content -LiteralPath "apps/desktop/package.json" -Raw | ConvertFrom-Json).version
}
if (-not $SourceSha) {
    $SourceSha = (& git rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw "Could not resolve release source commit" }
}
if ($env:GITHUB_REF_TYPE -eq "tag" -and $env:GITHUB_REF_NAME -ne "v$Version") {
    throw "Tag $env:GITHUB_REF_NAME does not match package version $Version"
}
$actualSha = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actualSha -ne $SourceSha) {
    throw "Release validation source mismatch: expected $SourceSha, got $actualSha"
}

function Get-VaultInstallExecutable {
    $registryRoots = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    foreach ($root in $registryRoots) {
        if (-not (Test-Path $root)) { continue }
        foreach ($key in Get-ChildItem -Path $root -ErrorAction SilentlyContinue) {
            $item = Get-ItemProperty -Path $key.PSPath -ErrorAction SilentlyContinue
            if (-not $item -or $item.DisplayName -notlike "Vault Unified*") { continue }
            $candidates = @()

            $installLocation = Convert-RegistryPath $item.InstallLocation
            if ($installLocation) {
                $candidates += (Join-Path $installLocation "Vault Unified.exe")
            }

            $displayIcon = ([string]$item.DisplayIcon).Trim()
            $comma = $displayIcon.LastIndexOf(',')
            $iconIndex = 0
            if ($comma -gt 0 -and [int]::TryParse($displayIcon.Substring($comma + 1), [ref]$iconIndex)) {
                $displayIcon = $displayIcon.Substring(0, $comma)
            }
            $displayIcon = Convert-RegistryPath $displayIcon
            if ($displayIcon) {
                $candidates += $displayIcon
            }

            if ($item.UninstallString) {
                $uninstall = ([string]$item.UninstallString).Trim()
                if ($uninstall.StartsWith('"')) {
                    $quote = $uninstall.IndexOf('"', 1)
                    if ($quote -gt 1) {
                        $uninstallPath = $uninstall.Substring(1, $quote - 1)
                        $candidates += (Join-Path (Split-Path $uninstallPath) "Vault Unified.exe")
                    }
                }
            }

            foreach ($candidate in $candidates) {
                if ($candidate -and (Test-Path -LiteralPath $candidate)) {
                    return Get-Item -LiteralPath $candidate
                }
            }
        }
    }

    $direct = @(
        (Join-Path $env:LOCALAPPDATA "Vault Unified\Vault Unified.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Vault Unified\Vault Unified.exe"),
        (Join-Path $env:ProgramFiles "Vault Unified\Vault Unified.exe")
    )
    if (${env:ProgramFiles(x86)}) {
        $direct += (Join-Path ${env:ProgramFiles(x86)} "Vault Unified\Vault Unified.exe")
    }
    foreach ($candidate in $direct) {
        if (Test-Path -LiteralPath $candidate) {
            return Get-Item -LiteralPath $candidate
        }
    }
    return $null
}

function Wait-ForVaultExecutable {
    param([int]$Seconds = 45)
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        $app = Get-VaultInstallExecutable
        if ($app) { return $app }
        Start-Sleep -Seconds 1
    }
    throw "Vault Unified executable was not registered after installation"
}

function Stop-ProcessTree {
    param([int]$ProcessId)
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
}

function Launch-And-StopInstalledApp {
    param([System.IO.FileInfo]$App, [string]$DataDir)
    New-Item -ItemType Directory -Force -Path $DataDir | Out-Null
    $oldDataDir = $env:VAULT_DATA_DIR
    try {
        $env:VAULT_DATA_DIR = $DataDir
        $process = Start-Process -FilePath $App.FullName -PassThru
        Start-Sleep -Seconds 8
        if ($process.HasExited) {
            throw "Installed desktop application exited during launch smoke test with code $($process.ExitCode)"
        }
        Stop-ProcessTree -ProcessId $process.Id
        Start-Sleep -Seconds 2
    }
    finally {
        $env:VAULT_DATA_DIR = $oldDataDir
    }
}

function Smoke-PackagedSidecar {
    param([System.IO.FileInfo]$Sidecar)
    $smokeRoot = Join-Path $env:RUNNER_TEMP "vault-unified-sidecar-smoke"
    Remove-Item -LiteralPath $smokeRoot -Recurse -Force -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force -Path $smokeRoot | Out-Null
    $stdout = Join-Path $smokeRoot "sidecar.stdout.log"
    $stderr = Join-Path $smokeRoot "sidecar.stderr.log"
    $old = @{
        VAULT_DATA_DIR = $env:VAULT_DATA_DIR
        VAULT_API_HOST = $env:VAULT_API_HOST
        VAULT_API_PORT = $env:VAULT_API_PORT
        VAULT_API_ALLOW_REMOTE = $env:VAULT_API_ALLOW_REMOTE
        VAULT_API_DISABLE_DOCS = $env:VAULT_API_DISABLE_DOCS
    }
    try {
        $env:VAULT_DATA_DIR = Join-Path $smokeRoot "data"
        $env:VAULT_API_HOST = "127.0.0.1"
        $env:VAULT_API_PORT = "0"
        $env:VAULT_API_ALLOW_REMOTE = "0"
        $env:VAULT_API_DISABLE_DOCS = "1"
        $process = Start-Process -FilePath $Sidecar.FullName -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
        try {
            $readyLine = $null
            $deadline = [DateTime]::UtcNow.AddSeconds(45)
            while ([DateTime]::UtcNow -lt $deadline) {
                if (Test-Path -LiteralPath $stdout) {
                    $readyLine = Get-Content -LiteralPath $stdout -ErrorAction SilentlyContinue |
                        Where-Object { $_ -like "VAULT_API_READY *" } |
                        Select-Object -Last 1
                }
                if ($readyLine) { break }
                if ($process.HasExited) {
                    $detail = if (Test-Path $stderr) { Get-Content $stderr -Raw } else { "" }
                    throw "Packaged sidecar exited before readiness: $detail"
                }
                Start-Sleep -Milliseconds 250
            }
            if (-not $readyLine) { throw "Packaged sidecar did not emit its authenticated readiness handshake" }
            $ready = $readyLine.Substring("VAULT_API_READY ".Length) | ConvertFrom-Json
            if ($ready.host -ne "127.0.0.1" -or [int]$ready.port -le 0 -or ([string]$ready.bootstrap_secret).Length -lt 32) {
                throw "Packaged sidecar returned an invalid runtime handshake"
            }
            $base = "http://127.0.0.1:$($ready.port)/api"
            $headers = @{
                "X-Vault-Bootstrap" = [string]$ready.bootstrap_secret
                "X-Vault-Client" = "vault-unified-desktop"
            }
            $info = Invoke-RestMethod -Method Get -Uri "$base/auth/vault-info" -Headers $headers
            if ($info.exists -or $info.format -ne "missing") { throw "Disposable sidecar data directory was not empty" }

            $fakePassword = "generated-release-smoke-password-4V!e7z2L"
            $created = Invoke-RestMethod -Method Post -Uri "$base/auth/create" -Headers $headers -ContentType "application/json" -Body (@{
                password = $fakePassword
                confirm_password = $fakePassword
                remember = $false
            } | ConvertTo-Json -Compress)
            $headers["Authorization"] = "Bearer $($created.token)"
            $info = Invoke-RestMethod -Method Get -Uri "$base/auth/vault-info" -Headers $headers
            if (-not $info.exists -or $info.format -ne "v3") { throw "Packaged sidecar did not create a v3 vault" }

            $entry = Invoke-RestMethod -Method Post -Uri "$base/entries" -Headers $headers -ContentType "application/json" -Body (@{
                title = "Generated release smoke account"
                username = "generated-user"
                password = "generated-entry-secret-9J!p"
                url = "https://example.invalid/release-smoke"
                notes = "generated note"
                tags = @("generated", "release-smoke")
            } | ConvertTo-Json -Compress)
            $patched = Invoke-RestMethod -Method Patch -Uri "$base/entries/$($entry.id)" -Headers $headers -ContentType "application/json" -Body (@{
                password = ""
                notes = ""
            } | ConvertTo-Json -Compress)
            if ($patched.password -ne "" -or $patched.notes -ne "" -or $patched.has_password -or $patched.has_notes) {
                throw "Packaged sidecar did not preserve explicit empty secret updates"
            }
            $entries = @(Invoke-RestMethod -Method Get -Uri "$base/entries" -Headers $headers)
            if ($entries.Count -ne 1) { throw "Packaged sidecar CRUD smoke returned $($entries.Count) entries" }

            $backup = Invoke-RestMethod -Method Post -Uri "$base/backups/create" -Headers $headers -ContentType "application/json" -Body "{}"
            if (-not $backup.created.verified -or -not (Test-Path -LiteralPath ([string]$backup.created.path))) {
                throw "Packaged sidecar did not create and verify an encrypted backup"
            }
            $prefs = Invoke-RestMethod -Method Get -Uri "$base/sync/preferences" -Headers $headers
            if (@($prefs.enabled_sources).Count -ne 0 -or $prefs.auto_push_on_edit -or $prefs.auto_pull_on_sync) {
                throw "Packaged sidecar did not apply conservative local-only sync defaults"
            }
            $direct = Invoke-WebRequest -Method Post -Uri "$base/sync/push" -Headers $headers -ContentType "application/json" -Body "{}" -SkipHttpErrorCheck
            if ([int]$direct.StatusCode -ne 409 -or $direct.Content -notmatch "preview") {
                throw "Packaged sidecar allowed direct desktop sync without preview"
            }
        }
        finally {
            if ($process -and -not $process.HasExited) { Stop-ProcessTree -ProcessId $process.Id }
        }
    }
    finally {
        foreach ($name in $old.Keys) {
            if ($null -eq $old[$name]) {
                Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue
            } else {
                Set-Item -Path "Env:$name" -Value $old[$name]
            }
        }
    }
}

$bundleRoot = Join-Path $RepoRoot "apps\desktop\src-tauri\target\release\bundle"
$nsisFiles = @(Get-ChildItem -LiteralPath (Join-Path $bundleRoot "nsis") -Filter "*-setup.exe" -File)
$msiFiles = @(Get-ChildItem -LiteralPath (Join-Path $bundleRoot "msi") -Filter "*.msi" -File)
if ($nsisFiles.Count -ne 1 -or $msiFiles.Count -ne 1) {
    throw "Expected exactly one NSIS and one MSI installer; found $($nsisFiles.Count) and $($msiFiles.Count)"
}
$nsis = $nsisFiles[0]
$msi = $msiFiles[0]
if ($nsis.Length -le 0 -or $msi.Length -le 0) { throw "Installer asset is empty" }
$sidecar = Get-Item -LiteralPath (Join-Path $RepoRoot "apps\desktop\src-tauri\binaries\vault-api-sidecar-x86_64-pc-windows-msvc.exe")
if ($sidecar.Length -le 0) { throw "Packaged API sidecar is empty" }

Write-Host "=== Packaged sidecar generated-data smoke ==="
Smoke-PackagedSidecar -Sidecar $sidecar

Write-Host "=== NSIS install / launch / uninstall smoke ==="
$nsisInstall = Start-Process -FilePath $nsis.FullName -ArgumentList "/S" -PassThru -Wait
if ($nsisInstall.ExitCode -ne 0) { throw "NSIS silent install failed with $($nsisInstall.ExitCode)" }
$nsisApp = Wait-ForVaultExecutable
Launch-And-StopInstalledApp -App $nsisApp -DataDir (Join-Path $env:RUNNER_TEMP "vault-unified-nsis-app-data")
$uninstaller = Get-ChildItem -LiteralPath $nsisApp.DirectoryName -Filter "uninstall*.exe" -File -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $uninstaller) { throw "NSIS uninstaller was not found beside the installed application" }
$nsisUninstall = Start-Process -FilePath $uninstaller.FullName -ArgumentList "/S" -PassThru -Wait
if ($nsisUninstall.ExitCode -ne 0) { throw "NSIS silent uninstall failed with $($nsisUninstall.ExitCode)" }
Start-Sleep -Seconds 3

Write-Host "=== MSI install / launch / uninstall smoke ==="
$msiInstall = Start-Process -FilePath msiexec.exe -ArgumentList "/i `"$($msi.FullName)`" /qn /norestart" -PassThru -Wait
if (@(0, 3010) -notcontains $msiInstall.ExitCode) { throw "MSI install failed with $($msiInstall.ExitCode)" }
$msiApp = Wait-ForVaultExecutable
Launch-And-StopInstalledApp -App $msiApp -DataDir (Join-Path $env:RUNNER_TEMP "vault-unified-msi-app-data")
$msiUninstall = Start-Process -FilePath msiexec.exe -ArgumentList "/x `"$($msi.FullName)`" /qn /norestart" -PassThru -Wait
if (@(0, 3010) -notcontains $msiUninstall.ExitCode) { throw "MSI uninstall failed with $($msiUninstall.ExitCode)" }

$assetRecords = @()
foreach ($asset in @($nsis, $msi)) {
    $assetRecords += [ordered]@{
        name = $asset.Name
        bytes = [int64]$asset.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $asset.FullName).Hash.ToLowerInvariant()
        authenticode_status = [string](Get-AuthenticodeSignature -LiteralPath $asset.FullName).Status
    }
}
$manifest = [ordered]@{
    schema = 1
    version = $Version
    tag = "v$Version"
    source_commit = $SourceSha
    generated_utc = [DateTime]::UtcNow.ToString("o")
    validation = [ordered]@{
        python_tests = "passed-by-required-job"
        desktop_build = "passed-by-required-job"
        rust_tests = "passed-by-required-job"
        rustsec = "passed-by-required-job"
        packaged_sidecar_generated_data_smoke = "passed"
        nsis_install_launch_uninstall = "passed"
        msi_install_launch_uninstall = "passed"
    }
    assets = $assetRecords
}
$manifestPath = Join-Path $RepoRoot "release-manifest-v$Version.json"
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Host "Release manifest: $manifestPath"
Get-Content -LiteralPath $manifestPath
