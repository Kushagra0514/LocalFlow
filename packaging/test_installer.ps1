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
$DataRoot = Join-Path $TestRoot "data"
$FreshDataRoot = Join-Path $TestRoot "fresh-data"
$ExpectedPrefix = $RepoRoot + [IO.Path]::DirectorySeparatorChar + ".local" + [IO.Path]::DirectorySeparatorChar
$OldDataDirectory = $env:LOCALFLOW_DATA_DIR

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

    if (-not (Test-Path -LiteralPath (Join-Path $InstallRoot "config.default.ini"))) {
        throw "Installer did not install config.default.ini"
    }
    $Executable = Join-Path $InstallRoot "LocalFlow.exe"
    $env:LOCALFLOW_DATA_DIR = $FreshDataRoot
    & $Executable --check-config
    if ($LASTEXITCODE -ne 0) {
        throw "Fresh installation did not create a valid default config"
    }
    $FreshConfig = Join-Path $FreshDataRoot "config.ini"
    $FreshContents = Get-Content -LiteralPath $FreshConfig -Raw
    if ($FreshContents -notmatch "(?ms)^\[cleanup\]\r?\nenabled = false\r?$" -or
        $FreshContents -notmatch "(?ms)^\[commands\]\r?\nenabled = false\r?$") {
        throw "Fresh installation did not preserve safe cloud defaults"
    }
    $LegacyConfig = Join-Path $InstallRoot "config.txt"
    $LegacyContents = "HOTKEY=f12`r`nAUTO_PASTE=true`r`nCLEANUP=true`r`n"
    Set-Content -LiteralPath $LegacyConfig -Value $LegacyContents -NoNewline
    $env:LOCALFLOW_DATA_DIR = $DataRoot
    & $Executable --check-config
    if ($LASTEXITCODE -ne 0) {
        throw "Installed LocalFlow.exe failed to migrate and check config"
    }
    $LiveConfig = Join-Path $DataRoot "config.ini"
    if (-not (Test-Path -LiteralPath $LiveConfig)) {
        throw "Installed application did not create the user-data config.ini"
    }
    $LiveContents = Get-Content -LiteralPath $LiveConfig -Raw
    if ($LiveContents -notmatch "(?m)^dictation = f12\r?$" -or
        $LiveContents -notmatch "(?m)^auto_paste = true\r?$" -or
        $LiveContents -notmatch "(?ms)^\[cleanup\]\r?\nenabled = false\r?$") {
        throw "Legacy migration did not preserve hotkey/paste with cleanup disabled"
    }

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
    if ((Get-Content -LiteralPath $LegacyConfig -Raw) -ne $LegacyContents) {
        throw "Installer upgrade changed the legacy config.txt rollback file"
    }
    if ((Get-Content -LiteralPath $LiveConfig -Raw) -ne $LiveContents) {
        throw "Installer upgrade replaced the user-data config.ini"
    }
    if (Test-Path -LiteralPath (Join-Path $InstallRoot "config.ini")) {
        throw "Installer placed a live config.ini beside LocalFlow.exe"
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
            $_.Extension -in @(".bin", ".gguf", ".part") -or
            $_.Name -match "(?i)llama|s1-mini|S1_MINI"
        }
    if ($ForbiddenFiles) {
        throw "Installed application contains obsolete local-cleanup files: $($ForbiddenFiles.FullName -join ', ')"
    }

    & $Executable --version
    if ($LASTEXITCODE -ne 0) {
        throw "Installed LocalFlow.exe failed with exit code $LASTEXITCODE"
    }
    $ReportedConfig = & $Executable --config-path
    if ($LASTEXITCODE -ne 0 -or $ReportedConfig.Trim() -ne $LiveConfig) {
        throw "Installed LocalFlow.exe reported the wrong live config path"
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
    $env:LOCALFLOW_DATA_DIR = $OldDataDirectory
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
