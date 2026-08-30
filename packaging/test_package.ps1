param(
    [string]$Package = "",
    [string]$ModelSeedDirectory = "",
    [string]$Sample = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if (-not $Package) {
    $Package = Join-Path $RepoRoot "dist\LocalFlow-windows-x64.zip"
}
if (-not $ModelSeedDirectory) {
    $ModelSeedDirectory = Join-Path $RepoRoot ".local\phase1\models"
}
if (-not $Sample) {
    $Sample = Join-Path $RepoRoot ".local\phase1\samples\jfk.wav"
}
$TestRoot = Join-Path $RepoRoot ".local\package-test\$([Guid]::NewGuid())"
$InstallRoot = Join-Path $TestRoot "install"
$CacheRoot = Join-Path $TestRoot "cache"
$ModelRoot = Join-Path $CacheRoot "models"
$OldDataDirectory = $env:LOCALFLOW_DATA_DIR

try {
    New-Item -ItemType Directory -Force -Path $InstallRoot, $ModelRoot | Out-Null
    Expand-Archive -LiteralPath $Package -DestinationPath $InstallRoot
    Copy-Item `
        -LiteralPath (Join-Path $ModelSeedDirectory "ggml-base.en-q5_1.bin") `
        -Destination $ModelRoot
    $ForbiddenFiles = Get-ChildItem -LiteralPath $InstallRoot -File -Recurse |
        Where-Object {
            $_.Extension -ieq ".gguf" -or
            $_.Name -match "(?i)llama|s1-mini|S1_MINI"
        }
    if ($ForbiddenFiles) {
        throw "Package contains obsolete local-cleanup files: $($ForbiddenFiles.FullName -join ', ')"
    }

    $env:LOCALFLOW_DATA_DIR = $CacheRoot
    & (Join-Path $InstallRoot "LocalFlow.exe") --verify-installation
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged installation verification failed with exit code $LASTEXITCODE"
    }
    & (Join-Path $InstallRoot "LocalFlow.exe") --smoke-test $Sample
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged end-to-end smoke test failed with exit code $LASTEXITCODE"
    }
}
finally {
    $env:LOCALFLOW_DATA_DIR = $OldDataDirectory
    $FullTestRoot = [IO.Path]::GetFullPath($TestRoot)
    $ExpectedPrefix = $RepoRoot + [IO.Path]::DirectorySeparatorChar + ".local" + [IO.Path]::DirectorySeparatorChar
    if (-not $FullTestRoot.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove unexpected package-test path: $FullTestRoot"
    }
    if (Test-Path -LiteralPath $FullTestRoot) {
        Remove-Item -LiteralPath $FullTestRoot -Recurse -Force
    }
}

if (Test-Path -LiteralPath $TestRoot) {
    throw "Package-test removal left files behind at $TestRoot"
}
Write-Host "Whisper-only package contents, isolated smoke test, and removal passed."
