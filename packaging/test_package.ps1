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
    if (-not (Test-Path -LiteralPath (Join-Path $ModelSeedDirectory "ggml-base.en-q5_1.bin"))) {
        $ModelSeedDirectory = Join-Path $env:LOCALAPPDATA "LocalFlow\models"
    }
}
if (-not $Sample) {
    $Sample = Join-Path $RepoRoot ".local\phase1\samples\jfk.wav"
}
$TestRoot = Join-Path $RepoRoot ".local\package-test\$([Guid]::NewGuid())"
$InstallRoot = Join-Path $TestRoot "install"
$CacheRoot = Join-Path $TestRoot "cache"
$ModelRoot = Join-Path $CacheRoot "models"
$OldDataDirectory = $env:LOCALFLOW_DATA_DIR
$OldHttpsProxy = $env:HTTPS_PROXY
$OldGroqKey = $env:GROQ_API_KEY

try {
    New-Item -ItemType Directory -Force -Path $InstallRoot, $ModelRoot | Out-Null
    Expand-Archive -LiteralPath $Package -DestinationPath $InstallRoot
    if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot "config.default.ini"))) {
        throw "Package is missing config.default.ini"
    }
    if (Test-Path -LiteralPath (Join-Path $InstallRoot "config.txt")) {
        throw "Package still contains the retired live config.txt"
    }
    if (Test-Path -LiteralPath (Join-Path $InstallRoot "config.ini")) {
        throw "Package contains a live config.ini"
    }
    $Manifest = Get-Content -LiteralPath (Join-Path $InstallRoot "BUILD_MANIFEST.json") -Raw |
        ConvertFrom-Json
    if ($Manifest.version -ne "0.2.0" -or $Manifest.models_bundled) {
        throw "Package manifest has incorrect version or model-bundling metadata"
    }
    $DefaultConfig = Get-Content -LiteralPath (Join-Path $InstallRoot "config.default.ini") -Raw
    if ($DefaultConfig -notmatch "(?ms)^\[cleanup\]\r?\nenabled = false\r?$" -or
        $DefaultConfig -notmatch "(?ms)^\[commands\]\r?\nenabled = false\r?$") {
        throw "Packaged defaults do not disable cloud cleanup and commands"
    }
    Copy-Item `
        -LiteralPath (Join-Path $ModelSeedDirectory "ggml-base.en-q5_1.bin") `
        -Destination $ModelRoot
    $ForbiddenFiles = Get-ChildItem -LiteralPath $InstallRoot -File -Recurse |
        Where-Object {
            $_.Extension -in @(".bin", ".gguf", ".part") -or
            $_.Name -match "(?i)llama|s1-mini|S1_MINI"
        }
    if ($ForbiddenFiles) {
        throw "Package contains obsolete local-cleanup files: $($ForbiddenFiles.FullName -join ', ')"
    }

    $env:LOCALFLOW_DATA_DIR = $CacheRoot
    $env:HTTPS_PROXY = "http://127.0.0.1:1"
    $env:GROQ_API_KEY = "package-test-placeholder"
    & (Join-Path $InstallRoot "LocalFlow.exe") --verify-installation
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged installation verification failed with exit code $LASTEXITCODE"
    }
    $LiveConfig = Join-Path $CacheRoot "config.ini"
    if (-not (Test-Path -LiteralPath $LiveConfig)) {
        throw "Packaged application did not create the canonical config.ini"
    }
    $LiveContents = Get-Content -LiteralPath $LiveConfig -Raw
    if ($LiveContents -notmatch "(?ms)^\[cleanup\]\r?\nenabled = false\r?$" -or
        $LiveContents -notmatch "(?ms)^\[commands\]\r?\nenabled = false\r?$") {
        throw "Packaged smoke-test configuration enabled a cloud feature"
    }
    & (Join-Path $InstallRoot "LocalFlow.exe") --smoke-test $Sample
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged end-to-end smoke test failed with exit code $LASTEXITCODE"
    }
}
finally {
    $env:LOCALFLOW_DATA_DIR = $OldDataDirectory
    $env:HTTPS_PROXY = $OldHttpsProxy
    $env:GROQ_API_KEY = $OldGroqKey
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
