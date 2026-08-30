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
    $InstallLog = Join-Path $TestRoot "install.log"
    $Install = Start-Process -FilePath $Installer -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-",
        "/DIR=$InstallRoot", "/LOG=$InstallLog"
    ) -Wait -PassThru -WindowStyle Hidden
    if ($Install.ExitCode -ne 0) {
        $Details = if (Test-Path -LiteralPath $InstallLog) {
            Get-Content -LiteralPath $InstallLog -Raw
        } else {
            "Installer did not create a log."
        }
        throw "Installer failed with exit code $($Install.ExitCode):`n$Details"
    }

    $Config = Join-Path $InstallRoot "config.txt"
    $CustomConfig = "HOTKEY=f12`r`nAUTO_PASTE=true`r`n"
    Set-Content -LiteralPath $Config -Value $CustomConfig -NoNewline

    $ObsoleteRuntime = Join-Path $InstallRoot "runtime\llama"
    $LicenseRoot = Join-Path $InstallRoot "licenses"
    New-Item -ItemType Directory -Force -Path $ObsoleteRuntime, $LicenseRoot | Out-Null
    Set-Content -LiteralPath (Join-Path $ObsoleteRuntime "llama-server.exe") -Value "obsolete"
    foreach ($License in @(
        "LLAMA_CPP_LICENSE.txt",
        "S1_MINI_LICENSE.txt",
        "S1_MINI_NOTICE.txt"
    )) {
        Set-Content -LiteralPath (Join-Path $LicenseRoot $License) -Value "obsolete"
    }

    $Upgrade = Start-Process -FilePath $Installer -ArgumentList @(
        "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/DIR=$InstallRoot"
    ) -Wait -PassThru -WindowStyle Hidden
    if ($Upgrade.ExitCode -ne 0) {
        throw "Installer upgrade failed with exit code $($Upgrade.ExitCode)"
    }
    if ((Get-Content -LiteralPath $Config -Raw) -ne $CustomConfig) {
        throw "Installer upgrade replaced the user's config.txt"
    }
    if (Test-Path -LiteralPath $ObsoleteRuntime) {
        throw "Installer upgrade left the obsolete runtime\llama directory behind"
    }
    foreach ($License in @(
        "LLAMA_CPP_LICENSE.txt",
        "S1_MINI_LICENSE.txt",
        "S1_MINI_NOTICE.txt"
    )) {
        if (Test-Path -LiteralPath (Join-Path $LicenseRoot $License)) {
            throw "Installer upgrade left obsolete license $License behind"
        }
    }
    $ForbiddenFiles = Get-ChildItem -LiteralPath $InstallRoot -File -Recurse |
        Where-Object {
            $_.Extension -ieq ".gguf" -or
            $_.Name -match "(?i)llama|s1-mini|S1_MINI"
        }
    if ($ForbiddenFiles) {
        throw "Installed application contains obsolete local-cleanup files: $($ForbiddenFiles.FullName -join ', ')"
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
Write-Host "Silent install, precise obsolete-file cleanup, config-preserving upgrade, launch, and uninstall passed."
