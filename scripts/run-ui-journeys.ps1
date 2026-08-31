[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$desktopRoot = Join-Path $repoRoot "apps\desktop"
$runtimeRoot = Join-Path $desktopRoot ".playwright-runtime"
$markerFile = Join-Path $runtimeRoot "secret-markers.txt"
$scanner = Join-Path $PSScriptRoot "scan-ui-artifacts.ps1"
$playwright = Join-Path $desktopRoot "node_modules\.bin\playwright.cmd"

if (-not (Test-Path -LiteralPath $playwright -PathType Leaf)) {
    throw "Playwright is not installed. Run npm ci in apps/desktop first."
}

New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
$runId = [Guid]::NewGuid().ToString("N")
$env:UI_TEST_RUN_ID = $runId
$env:UI_TEST_MASTER_PASSWORD = "generated-master-$runId-A9!"
$env:UI_TEST_ENTRY_PASSWORD = "generated-entry-$runId-Z7!"
$env:UI_TEST_BEARER_TOKEN = "generated-bearer-$runId"
$env:UI_TEST_BOOTSTRAP_SECRET = "generated-bootstrap-$runId"

$markers = @(
    $env:UI_TEST_MASTER_PASSWORD,
    $env:UI_TEST_ENTRY_PASSWORD,
    $env:UI_TEST_BEARER_TOKEN,
    $env:UI_TEST_BOOTSTRAP_SECRET
)
[System.IO.File]::WriteAllLines(
    $markerFile,
    $markers,
    [System.Text.UTF8Encoding]::new($false)
)

$journeyExit = 1
Push-Location $desktopRoot
try {
    & $playwright test
    $journeyExit = $LASTEXITCODE
}
finally {
    Pop-Location
}

$scanExit = 1
try {
    & $scanner `
        -MarkerFile $markerFile `
        -ArtifactPath @(
            (Join-Path $desktopRoot "test-results"),
            (Join-Path $desktopRoot "playwright-report")
        ) `
        -DeleteUnsafeGeneratedArtifacts
    $scanExit = $LASTEXITCODE
}
catch {
    Write-Error "UI artifact safety scan failed. No artifacts may be uploaded."
}

if ($scanExit -ne 0) {
    exit $scanExit
}
exit $journeyExit
