# One-click desktop dev: API + Tauri
$ErrorActionPreference = "Stop"

# apps/desktop -> repo root
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not (Test-Path (Join-Path $root "pyproject.toml"))) {
    Write-Error "Could not locate repo root from script at $PSScriptRoot (expected pyproject.toml at $root)"
    exit 1
}

& (Join-Path $root "launch-desktop.ps1")
