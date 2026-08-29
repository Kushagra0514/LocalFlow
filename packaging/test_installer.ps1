param(
    [string]$Installer = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if (-not $Installer) {
    $Installer = Join-Path $RepoRoot "dist\LocalFlow-Setup.exe"
}
$TestRoot = Join-Path $RepoRoot ".local\installer-test\$([Guid]::NewGuid())"
$InstallRoot = Join-Path $TestRoot "LocalFlow"
$ExpectedPrefix = $RepoRoot + [IO.Path]::DirectorySeparatorChar + ".local" + [IO.Path]::DirectorySeparatorChar

try {
    New-Item -ItemType Directory -Force -Path $TestRoot | Out-Null
    $Install = Start-Process -FilePath $Installer -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=$InstallRoot"
    ) -Wait -PassThru -WindowStyle Hidden
    if ($Install.ExitCode -ne 0) {
        throw "Installer failed with exit code $($Install.ExitCode)"
    }

    $Config = Join-Path $InstallRoot "config.txt"
    $CustomConfig = "HOTKEY=f12`r`nAUTO_PASTE=true`r`n"
    Set-Content -LiteralPath $Config -Value $CustomConfig -NoNewline
    $Upgrade = Start-Process -FilePath $Installer -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=$InstallRoot"
    ) -Wait -PassThru -WindowStyle Hidden
    if ($Upgrade.ExitCode -ne 0) {
        throw "Installer upgrade failed with exit code $($Upgrade.ExitCode)"
    }
    if ((Get-Content -LiteralPath $Config -Raw) -ne $CustomConfig) {
        throw "Installer upgrade replaced the user's config.txt"
    }

    $Executable = Join-Path $InstallRoot "LocalFlow.exe"
    & $Executable --version
    if ($LASTEXITCODE -ne 0) {
        throw "Installed LocalFlow.exe failed with exit code $LASTEXITCODE"
    }

    $Uninstaller = Join-Path $InstallRoot "unins000.exe"
    $Uninstall = Start-Process -FilePath $Uninstaller -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"
    ) -Wait -PassThru -WindowStyle Hidden
    if ($Uninstall.ExitCode -ne 0) {
        throw "Uninstaller failed with exit code $($Uninstall.ExitCode)"
    }
}
finally {
    $FullTestRoot = [IO.Path]::GetFullPath($TestRoot)
    if (-not $FullTestRoot.StartsWith($ExpectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove unexpected installer-test path: $FullTestRoot"
    }
    if (Test-Path -LiteralPath $FullTestRoot) {
        Remove-Item -LiteralPath $FullTestRoot -Recurse -Force
    }
}

if (Test-Path -LiteralPath $TestRoot) {
    throw "Installer-test removal left files behind at $TestRoot"
}
Write-Host "Silent install, config-preserving upgrade, launch, uninstall, and cleanup passed."
