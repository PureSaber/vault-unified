# One-click desktop dev: API + Tauri
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not (Test-Path "$root\pyproject.toml")) { $root = "C:\develop\token&password" }

& "$root\launch-desktop.ps1"
