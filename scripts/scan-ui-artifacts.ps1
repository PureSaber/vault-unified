[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$MarkerFile,

    [Parameter(Mandatory = $true)]
    [string[]]$ArtifactPath,

    [switch]$DeleteUnsafeGeneratedArtifacts
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.IO.Compression.FileSystem

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$desktopRoot = (Resolve-Path (Join-Path $repoRoot "apps\desktop")).Path
$allowedLeafNames = @("test-results", "playwright-report")
$resolvedMarker = [System.IO.Path]::GetFullPath($MarkerFile)

function Test-ContainsMarker {
    param(
        [byte[]]$Bytes,
        [string[]]$Markers
    )

    $text = [System.Text.Encoding]::UTF8.GetString($Bytes)
    foreach ($marker in $Markers) {
        if ($text.IndexOf($marker, [System.StringComparison]::Ordinal) -ge 0) {
            return $true
        }
    }
    return $false
}

function Test-ArtifactFile {
    param(
        [System.IO.FileInfo]$File,
        [string[]]$Markers
    )

    if ($File.Extension -ieq ".zip") {
        $archive = [System.IO.Compression.ZipFile]::OpenRead($File.FullName)
        try {
            foreach ($entry in $archive.Entries) {
                if ($entry.Length -eq 0) { continue }
                $stream = $entry.Open()
                $memory = [System.IO.MemoryStream]::new()
                try {
                    $stream.CopyTo($memory)
                    if (Test-ContainsMarker -Bytes $memory.ToArray() -Markers $Markers) {
                        return $true
                    }
                }
                finally {
                    $memory.Dispose()
                    $stream.Dispose()
                }
            }
            return $false
        }
        finally {
            $archive.Dispose()
        }
    }

    return Test-ContainsMarker -Bytes ([System.IO.File]::ReadAllBytes($File.FullName)) -Markers $Markers
}

$safeSentinel = Join-Path $desktopRoot "test-results\.artifacts-safe"
try {
    if (-not (Test-Path -LiteralPath $resolvedMarker -PathType Leaf)) {
        throw "Generated UI secret-marker file is missing"
    }
    $markers = @(Get-Content -LiteralPath $resolvedMarker | Where-Object { $_.Length -gt 0 })
    if ($markers.Count -lt 4) {
        throw "Generated UI secret-marker file is incomplete"
    }

    $unsafe = [System.Collections.Generic.List[System.IO.FileInfo]]::new()
    foreach ($candidate in $ArtifactPath) {
        $fullPath = [System.IO.Path]::GetFullPath($candidate)
        $leaf = Split-Path -Leaf $fullPath
        if (
            $allowedLeafNames -notcontains $leaf -or
            -not $fullPath.StartsWith($desktopRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)
        ) {
            throw "Refusing to scan or delete outside an approved UI artifact directory"
        }
        if (-not (Test-Path -LiteralPath $fullPath -PathType Container)) { continue }
        foreach ($file in Get-ChildItem -LiteralPath $fullPath -Recurse -File) {
            if (Test-ArtifactFile -File $file -Markers $markers) {
                $unsafe.Add($file)
            }
        }
    }

    if ($unsafe.Count -gt 0 -and -not $DeleteUnsafeGeneratedArtifacts) {
        throw "Generated UI credentials were found in one or more artifacts"
    }
    foreach ($file in $unsafe) {
        Remove-Item -LiteralPath $file.FullName -Force
        Write-Warning ("Removed unsafe generated UI artifact: " + $file.FullName)
    }

    $safeRoot = Split-Path -Parent $safeSentinel
    New-Item -ItemType Directory -Force -Path $safeRoot | Out-Null
    [System.IO.File]::WriteAllText(
        $safeSentinel,
        "Generated-data artifact marker scan passed.",
        [System.Text.UTF8Encoding]::new($false)
    )
    Write-Output ("UI artifact scan passed; removed unsafe files: " + $unsafe.Count)
}
finally {
    if (Test-Path -LiteralPath $resolvedMarker -PathType Leaf) {
        Remove-Item -LiteralPath $resolvedMarker -Force
    }
}
