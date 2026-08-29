param(
    [switch]$SkipApplicationBuild
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$AppExecutable = Join-Path $RepoRoot "dist\LocalFlow\LocalFlow.exe"
$Installer = Join-Path $RepoRoot "dist\LocalFlow-Setup.exe"

if (-not $SkipApplicationBuild) {
    & (Join-Path $PSScriptRoot "build_windows.ps1")
    if ($LASTEXITCODE -ne 0) {
        throw "LocalFlow application build failed with exit code $LASTEXITCODE"
    }
}
if (-not (Test-Path -LiteralPath $AppExecutable)) {
    throw "Packaged application is missing: $AppExecutable"
}

$InnoRoots = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 7\ISCC.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 7\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
)
if (${env:ProgramFiles(x86)}) {
    $InnoRoots += Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
}
$Command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
$Compiler = if ($Command) {
    $Command.Source
} else {
    $InnoRoots | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $Compiler) {
    throw "Inno Setup is required. Install it with: winget install --id JRSoftware.InnoSetup -e"
}

& $Compiler (Join-Path $PSScriptRoot "LocalFlow.iss")
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $Installer)) {
    throw "Inno Setup failed to create $Installer"
}

$Hash = (Get-FileHash -LiteralPath $Installer -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Built $Installer"
Write-Host "SHA-256: $Hash"
