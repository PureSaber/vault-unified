param(
    [string]$Version = "",
    [string]$SourceSha = "",
    [string]$RepoRoot = (Join-Path $PSScriptRoot ".."),
    [switch]$SkipInstallerLifecycle
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "pyproject.toml"))) {
    throw "Invalid repository root"
}
Set-Location -LiteralPath $RepoRoot
$ValidationTempRoot = if ($env:RUNNER_TEMP) {
    $env:RUNNER_TEMP
} elseif ($env:TEMP) {
    $env:TEMP
} else {
    [IO.Path]::GetTempPath()
}

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
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
& $VenvPython (Join-Path $RepoRoot "scripts\version_contract.py") --repo-root $RepoRoot --expect $Version | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Release component version contract failed" }
$actualSha = (& git rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $actualSha -ne $SourceSha) {
    throw "Release validation source mismatch: expected $SourceSha, got $actualSha"
}

function Convert-RegistryPath {
    param([object]$Value)
    if ($null -eq $Value) { return "" }
    $text = ([string]$Value).Trim()
    if ($text.Length -ge 2 -and $text.StartsWith('"') -and $text.EndsWith('"')) {
        $text = $text.Substring(1, $text.Length - 2)
    }
    return $text.Trim('"')
}

function Get-VaultUninstallEntries {
    $registryRoots = @(
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
    )
    $entries = @()
    foreach ($root in $registryRoots) {
        if (-not (Test-Path $root)) { continue }
        foreach ($key in Get-ChildItem -Path $root -ErrorAction SilentlyContinue) {
            $item = Get-ItemProperty -Path $key.PSPath -ErrorAction SilentlyContinue
            if (-not $item -or $item.DisplayName -notlike "Vault Unified*") { continue }
            $entries += $item
        }
    }
    return $entries
}

function Get-VaultInstallExecutable {
    param([switch]$DeepSearch)
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
                $candidates += (Join-Path $installLocation "vault-unified-desktop.exe")
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
    if ($DeepSearch) {
        $searchRoots = @(
            $env:LOCALAPPDATA,
            $env:ProgramFiles,
            ${env:ProgramFiles(x86)}
        ) | Where-Object { $_ } | Select-Object -Unique
        foreach ($root in $searchRoots) {
            if (-not (Test-Path -LiteralPath $root)) { continue }
            foreach ($fileName in @("Vault Unified.exe", "vault-unified-desktop.exe")) {
                $found = Get-ChildItem -LiteralPath $root -Filter $fileName -File -Recurse -ErrorAction SilentlyContinue |
                    Select-Object -First 1
                if ($found) { return $found }
            }
        }
    }
    return $null
}

function Wait-ForVaultExecutable {
    param([int]$Seconds = 45)
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    $deepSearchAttempted = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        $app = Get-VaultInstallExecutable
        if ($app) { return $app }
        if (-not $deepSearchAttempted) {
            $deepSearchAttempted = $true
            $app = Get-VaultInstallExecutable -DeepSearch
            if ($app) { return $app }
        }
        Start-Sleep -Seconds 1
    }
    throw "Vault Unified executable was not registered after installation"
}

function Wait-ForVaultUninstalled {
    param([string]$InstallDirectory, [int]$Seconds = 45)
    $normalized = [IO.Path]::GetFullPath($InstallDirectory).TrimEnd(
        [IO.Path]::DirectorySeparatorChar,
        [IO.Path]::AltDirectorySeparatorChar
    )
    if (-not $normalized -or $normalized -eq [IO.Path]::GetPathRoot($normalized)) {
        throw "Refusing to validate an unsafe installer cleanup path: $InstallDirectory"
    }
    $prefix = $normalized + [IO.Path]::DirectorySeparatorChar
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    do {
        $registrations = @(Get-VaultUninstallEntries)
        $running = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
            $path = [string]$_.ExecutablePath
            $path -and (
                $path.Equals($normalized, [StringComparison]::OrdinalIgnoreCase) -or
                $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
            )
        })
        $directoryExists = Test-Path -LiteralPath $normalized
        if (-not $directoryExists -and $registrations.Count -eq 0 -and $running.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)

    $registrationNames = ($registrations | ForEach-Object {
        "$($_.DisplayName) $($_.DisplayVersion)"
    }) -join ", "
    $processNames = ($running | ForEach-Object { "$($_.Name):$($_.ProcessId)" }) -join ", "
    throw (
        "Vault Unified uninstall cleanup did not complete: " +
        "install_directory_exists=$directoryExists; " +
        "registrations=$registrationNames; running_processes=$processNames"
    )
}

function Assert-BrowserBridgeRemoved {
    foreach ($browser in @("Google\Chrome", "Microsoft\Edge")) {
        $key = "HKCU:\Software\$browser\NativeMessagingHosts\org.vaultunified.desktop"
        if (Test-Path -LiteralPath $key) { throw "Uninstall left a browser bridge registration" }
    }
}

function Stop-ProcessTree {
    param([int]$ProcessId)
    & taskkill.exe /PID $ProcessId /T /F 2>$null | Out-Null
}

function Smoke-PackagedSidecar {
    param([System.IO.FileInfo]$Sidecar)
    $smokeRoot = Join-Path $ValidationTempRoot ("vault-unified-sidecar-smoke-" + [Guid]::NewGuid().ToString("N"))
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
        $process = Start-Process -WindowStyle Hidden -FilePath $Sidecar.FullName -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
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
            $cleanupPolicy = @{
                newest_count = 0
                daily_days = 0
                weekly_weeks = 0
            }
            $cleanupPreview = Invoke-RestMethod -Method Post -Uri "$base/backups/prune" -Headers $headers -ContentType "application/json" -Body (@{
                apply = $false
                newest_count = $cleanupPolicy.newest_count
                daily_days = $cleanupPolicy.daily_days
                weekly_weeks = $cleanupPolicy.weekly_weeks
            } | ConvertTo-Json -Compress)
            if (([string]$cleanupPreview.preview_token).Length -lt 32 -or -not $cleanupPreview.expires_at) {
                throw "Packaged sidecar backup cleanup preview did not issue a confirmation token"
            }
            $unconfirmedCleanup = Invoke-WebRequest -Method Post -Uri "$base/backups/prune" -Headers $headers -ContentType "application/json" -Body (@{
                apply = $true
                newest_count = $cleanupPolicy.newest_count
                daily_days = $cleanupPolicy.daily_days
                weekly_weeks = $cleanupPolicy.weekly_weeks
            } | ConvertTo-Json -Compress) -SkipHttpErrorCheck
            if ([int]$unconfirmedCleanup.StatusCode -ne 409) {
                throw "Packaged sidecar allowed backup cleanup without an approved preview"
            }
            if ([int]$cleanupPreview.delete_count -gt 0) {
                $cleanupApplied = Invoke-RestMethod -Method Post -Uri "$base/backups/prune" -Headers $headers -ContentType "application/json" -Body (@{
                    apply = $true
                    preview_token = [string]$cleanupPreview.preview_token
                    newest_count = $cleanupPolicy.newest_count
                    daily_days = $cleanupPolicy.daily_days
                    weekly_weeks = $cleanupPolicy.weekly_weeks
                } | ConvertTo-Json -Compress)
                if ([int]$cleanupApplied.deleted_count -ne [int]$cleanupPreview.delete_count) {
                    throw "Packaged sidecar did not execute the exact approved backup cleanup set"
                }
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
$nsisFiles = @(Get-ChildItem -LiteralPath (Join-Path $bundleRoot "nsis") -Filter "*_$($Version)_*-setup.exe" -File)
$msiFiles = @(Get-ChildItem -LiteralPath (Join-Path $bundleRoot "msi") -Filter "*_$($Version)_*.msi" -File)
if ($nsisFiles.Count -ne 1 -or $msiFiles.Count -ne 1) {
    throw "Expected exactly one NSIS and one MSI installer; found $($nsisFiles.Count) and $($msiFiles.Count)"
}
$nsis = $nsisFiles[0]
$msi = $msiFiles[0]
if ($nsis.Length -le 0 -or $msi.Length -le 0) { throw "Installer asset is empty" }
$sidecar = Get-Item -LiteralPath (Join-Path $RepoRoot "apps\desktop\src-tauri\binaries\vault-api-sidecar-x86_64-pc-windows-msvc.exe")
if ($sidecar.Length -le 0) { throw "Packaged API sidecar is empty" }
$extension = Get-Item -LiteralPath (Join-Path $RepoRoot "Vault-Unified-Browser-Extension-v$Version.zip")
& $VenvPython (Join-Path $RepoRoot "scripts\build_browser_extension.py") --repo-root $RepoRoot --verify $extension.FullName --expect-version $Version | Out-Host
if ($LASTEXITCODE -ne 0) { throw "Browser extension release ZIP validation failed" }

Write-Host "=== Packaged sidecar generated-data smoke ==="
Smoke-PackagedSidecar -Sidecar $sidecar

$nsisLifecycleStatus = "not-run-user-deferred"
$msiLifecycleStatus = "not-run-user-deferred"
if ($SkipInstallerLifecycle) {
    Write-Host "=== NSIS/MSI lifecycle smoke intentionally deferred; no installer was executed ==="
} else {
    if ($env:GITHUB_ACTIONS -ne "true" -or -not $env:RUNNER_TEMP) {
        throw "Installer lifecycle requires a disposable CI worker; use -SkipInstallerLifecycle for local artifact checks."
    }
    if (@(Get-VaultUninstallEntries).Count -ne 0) { throw "Disposable worker already has an installation" }
    $oldRelease = Join-Path $ValidationTempRoot ("vault-old-release-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $oldRelease | Out-Null
    gh release download v1.3.0 --repo PureSaber/vault-unified --dir $oldRelease --pattern "*-setup.exe" --pattern "*.msi" --pattern "release-manifest-v1.3.0.json"
    if ($LASTEXITCODE -ne 0) { throw "Could not download the published upgrade source" }
    $oldManifest = Get-Content (Join-Path $oldRelease "release-manifest-v1.3.0.json") -Raw | ConvertFrom-Json
    foreach ($record in $oldManifest.assets | Where-Object { $_.name -match '\.(exe|msi)$' }) {
        $asset = Join-Path $oldRelease ([string]$record.name).Replace(' ', '.')
        if (-not (Test-Path -LiteralPath $asset)) { $asset = Join-Path $oldRelease ([string]$record.name) }
        if ((Get-FileHash -Algorithm SHA256 -LiteralPath $asset).Hash.ToLowerInvariant() -ne $record.sha256) { throw "Published v1.3 installer integrity mismatch" }
    }
    $journey = Join-Path $RepoRoot "apps/desktop/tests/live/installed-vault-journey.mjs"
    $nsisData = Join-Path $ValidationTempRoot ("vault-upgrade-nsis-" + [Guid]::NewGuid().ToString("N"))
    $oldNsis = @(Get-ChildItem -LiteralPath $oldRelease -Filter "*-setup.exe" -File)
    if ($oldNsis.Count -ne 1) { throw "Expected the published v1.3 NSIS installer" }
    $oldInstall = Start-Process -WindowStyle Hidden -FilePath $oldNsis[0].FullName -ArgumentList "/S" -PassThru -Wait
    if ($oldInstall.ExitCode -ne 0) { throw "Old NSIS install failed" }
    $oldApp = Wait-ForVaultExecutable
    node $journey $oldApp.FullName $nsisData seed 1.3.0
    if ($LASTEXITCODE -ne 0) { throw "Could not create v1.3 installed fixture" }
    Write-Host "=== NSIS install / launch / uninstall smoke ==="
    $nsisInstall = Start-Process -WindowStyle Hidden -FilePath $nsis.FullName -ArgumentList "/S" -PassThru -Wait
    if ($nsisInstall.ExitCode -ne 0) { throw "NSIS silent install failed with $($nsisInstall.ExitCode)" }
    $nsisApp = Wait-ForVaultExecutable
    node $journey $nsisApp.FullName $nsisData reopen $Version initial
    if ($LASTEXITCODE -ne 0) { throw "NSIS upgrade lost data or failed installed checks" }
    $repair = Start-Process -WindowStyle Hidden -FilePath $nsis.FullName -ArgumentList "/S" -PassThru -Wait
    if ($repair.ExitCode -ne 0) { throw "NSIS retry failed" }
    node $journey $nsisApp.FullName $nsisData reopen $Version restart
    if ($LASTEXITCODE -ne 0) { throw "NSIS retry did not preserve the generated vault" }
    $uninstaller = Get-ChildItem -LiteralPath $nsisApp.DirectoryName -Filter "uninstall*.exe" -File -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $uninstaller) { throw "NSIS uninstaller was not found beside the installed application" }
    $nsisUninstall = Start-Process -WindowStyle Hidden -FilePath $uninstaller.FullName -ArgumentList "/S" -PassThru -Wait
    if ($nsisUninstall.ExitCode -ne 0) { throw "NSIS silent uninstall failed with $($nsisUninstall.ExitCode)" }
    Wait-ForVaultUninstalled -InstallDirectory $nsisApp.DirectoryName
    Assert-BrowserBridgeRemoved
    if (-not (Test-Path -LiteralPath (Join-Path $nsisData "generated.vault"))) { throw "NSIS uninstall removed vault data" }
    $nsisLifecycleStatus = "passed"

    $msiData = Join-Path $ValidationTempRoot ("vault-upgrade-msi-" + [Guid]::NewGuid().ToString("N"))
    $oldMsi = @(Get-ChildItem -LiteralPath $oldRelease -Filter "*.msi" -File)
    if ($oldMsi.Count -ne 1) { throw "Expected the published v1.3 MSI installer" }
    $oldInstall = Start-Process -WindowStyle Hidden -FilePath msiexec.exe -ArgumentList "/i `"$($oldMsi[0].FullName)`" /qn /norestart" -PassThru -Wait
    if (@(0, 3010) -notcontains $oldInstall.ExitCode) { throw "Old MSI install failed" }
    $oldApp = Wait-ForVaultExecutable
    node $journey $oldApp.FullName $msiData seed 1.3.0
    if ($LASTEXITCODE -ne 0) { throw "Could not create v1.3 MSI installed fixture" }
    Write-Host "=== MSI install / launch / uninstall smoke ==="
    $msiInstall = Start-Process -WindowStyle Hidden -FilePath msiexec.exe -ArgumentList "/i `"$($msi.FullName)`" /qn /norestart" -PassThru -Wait
    if (@(0, 3010) -notcontains $msiInstall.ExitCode) { throw "MSI install failed with $($msiInstall.ExitCode)" }
    $msiApp = Wait-ForVaultExecutable
    node $journey $msiApp.FullName $msiData reopen $Version initial
    if ($LASTEXITCODE -ne 0) { throw "MSI upgrade lost data or failed installed checks" }
    $repair = Start-Process -WindowStyle Hidden -FilePath msiexec.exe -ArgumentList "/fa `"$($msi.FullName)`" /qn /norestart" -PassThru -Wait
    if (@(0, 3010) -notcontains $repair.ExitCode) { throw "MSI repair failed" }
    node $journey $msiApp.FullName $msiData reopen $Version restart
    if ($LASTEXITCODE -ne 0) { throw "MSI repair/restart did not preserve the generated vault" }
    $msiUninstall = Start-Process -WindowStyle Hidden -FilePath msiexec.exe -ArgumentList "/x `"$($msi.FullName)`" /qn /norestart" -PassThru -Wait
    if (@(0, 3010) -notcontains $msiUninstall.ExitCode) { throw "MSI uninstall failed with $($msiUninstall.ExitCode)" }
    Wait-ForVaultUninstalled -InstallDirectory $msiApp.DirectoryName
    Assert-BrowserBridgeRemoved
    if (-not (Test-Path -LiteralPath (Join-Path $msiData "generated.vault"))) { throw "MSI uninstall removed vault data" }
    $msiLifecycleStatus = "passed"
}

$assetRecords = @()
foreach ($asset in @($nsis, $msi)) {
    $assetRecords += [ordered]@{
        name = $asset.Name
        bytes = [int64]$asset.Length
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $asset.FullName).Hash.ToLowerInvariant()
        authenticode_status = [string](Get-AuthenticodeSignature -LiteralPath $asset.FullName).Status
    }
}
$assetRecords += [ordered]@{
    name = $extension.Name
    bytes = [int64]$extension.Length
    sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $extension.FullName).Hash.ToLowerInvariant()
    kind = "browser_extension"
}
foreach ($path in @(
    ($nsis.FullName + ".sig"), ($msi.FullName + ".sig"),
    (Join-Path $RepoRoot "latest.json"),
    (Join-Path $RepoRoot "Vault-Unified-Personal-v$Version-Windows-x64.zip"),
    (Join-Path $RepoRoot "Vault-Unified-Sharing-Service-v$Version.zip")
)) {
    $asset = Get-Item -LiteralPath $path
    $assetRecords += [ordered]@{ name = $asset.Name; bytes = [int64]$asset.Length; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant(); kind = "personal_delivery" }
}
$manifest = [ordered]@{
    schema = 1
    version = $Version
    tag = "v$Version"
    source_commit = $SourceSha
    generated_utc = [DateTime]::UtcNow.ToString("o")
    validation = [ordered]@{
        source_checks = "See exact-head CI; not rerun by this installer validator"
        packaged_sidecar_generated_data_smoke = "passed"
        backup_cleanup_preview_confirmed = "passed"
        nsis_install_launch_uninstall = $nsisLifecycleStatus
        msi_install_launch_uninstall = $msiLifecycleStatus
        browser_extension_structure_permissions_and_version = "passed"
        nsis_v1_3_upgrade_retry_preserved_vault_and_bridge_removal = $nsisLifecycleStatus
        msi_v1_3_upgrade_restart_preserved_vault_and_bridge_removal = $msiLifecycleStatus
        installed_chrome_edge_save_fill_change_totp_passkey_reconnect_revoke = $nsisLifecycleStatus
    }
    assets = $assetRecords
}
$manifestPath = Join-Path $RepoRoot "release-manifest-v$Version.json"
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding utf8
Write-Host "Release manifest: $manifestPath"
Get-Content -LiteralPath $manifestPath
