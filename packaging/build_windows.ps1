param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$LocalRoot = Join-Path $RepoRoot ".local\packaging"
$DownloadRoot = Join-Path $LocalRoot "downloads"
$RuntimeRoot = Join-Path $LocalRoot "runtime"
$BuildRoot = Join-Path $LocalRoot "pyinstaller"
$DistRoot = Join-Path $RepoRoot "dist"
$PackageRoot = Join-Path $DistRoot "LocalFlow"
$PackageZip = Join-Path $DistRoot "LocalFlow-windows-x64.zip"
$env:UV_CACHE_DIR = Join-Path $LocalRoot "uv-cache"

function Assert-WorkspacePath([string]$Path) {
    $FullPath = [IO.Path]::GetFullPath($Path)
    $Prefix = $RepoRoot + [IO.Path]::DirectorySeparatorChar
    if (-not $FullPath.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the workspace: $FullPath"
    }
    return $FullPath
}

function Reset-Directory([string]$Path) {
    $FullPath = Assert-WorkspacePath $Path
    if (Test-Path -LiteralPath $FullPath) {
        Remove-Item -LiteralPath $FullPath -Recurse -Force
    }
    New-Item -ItemType Directory -Path $FullPath | Out-Null
}

function Get-VerifiedArtifact(
    [string]$Name,
    [string]$Uri,
    [string]$Sha256,
    [string]$Destination,
    [string]$Seed
) {
    New-Item -ItemType Directory -Force -Path (Split-Path $Destination) | Out-Null
    if (-not (Test-Path -LiteralPath $Destination) -and (Test-Path -LiteralPath $Seed)) {
        Copy-Item -LiteralPath $Seed -Destination $Destination
    }
    if (Test-Path -LiteralPath $Destination) {
        $Actual = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($Actual -eq $Sha256) {
            Write-Host "Verified cached $Name."
            return
        }
        Remove-Item -LiteralPath $Destination -Force
    }

    $Partial = "$Destination.part"
    if (Test-Path -LiteralPath $Partial) {
        Remove-Item -LiteralPath $Partial -Force
    }
    Write-Host "Downloading pinned $Name..."
    Invoke-WebRequest -Uri $Uri -OutFile $Partial
    $Actual = (Get-FileHash -LiteralPath $Partial -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Actual -ne $Sha256) {
        Remove-Item -LiteralPath $Partial -Force
        throw "$Name checksum mismatch: expected $Sha256, got $Actual"
    }
    Move-Item -LiteralPath $Partial -Destination $Destination
}

if (-not $IsWindows -or [Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne "X64") {
    throw "This package must be built on 64-bit Windows."
}

$WhisperArchive = Join-Path $DownloadRoot "whisper-b4938-bin-x64.zip"
$LlamaArchive = Join-Path $DownloadRoot "llama-b10516-bin-win-cpu-x64.zip"
Get-VerifiedArtifact `
    "whisper.cpp b4938" `
    "https://github.com/ggml-org/whisper.cpp/releases/download/b4938/whisper-bin-x64.zip" `
    "c2a4b60edb11f7e11a9191ffb50929535527d4d91c9903dbe3e554583bbbc63d" `
    $WhisperArchive `
    (Join-Path $RepoRoot ".local\phase1\downloads\whisper-b4938-x64.zip")
Get-VerifiedArtifact `
    "llama.cpp b10516" `
    "https://github.com/ggml-org/llama.cpp/releases/download/b10516/llama-b10516-bin-win-cpu-x64.zip" `
    "fbbbc55e0eb2e1b07f9dcb9488616c98ed47d9003b90e15e7c8c7812c4307cd3" `
    $LlamaArchive `
    (Join-Path $RepoRoot ".local\phase1\downloads\llama-b10516-win-cpu-x64.zip")

Reset-Directory $RuntimeRoot
$WhisperExpanded = Join-Path $LocalRoot "whisper-expanded"
$LlamaExpanded = Join-Path $LocalRoot "llama-expanded"
Reset-Directory $WhisperExpanded
Reset-Directory $LlamaExpanded
Expand-Archive -LiteralPath $WhisperArchive -DestinationPath $WhisperExpanded
Expand-Archive -LiteralPath $LlamaArchive -DestinationPath $LlamaExpanded

$WhisperTarget = Join-Path $RuntimeRoot "whisper\Release"
$LlamaTarget = Join-Path $RuntimeRoot "llama"
New-Item -ItemType Directory -Force -Path $WhisperTarget, $LlamaTarget | Out-Null
$WhisperFiles = @(
    "whisper-cli.exe", "whisper.dll", "ggml.dll", "ggml-base.dll",
    "ggml-cpu-x64.dll", "ggml-cpu-sse42.dll", "ggml-cpu-sandybridge.dll",
    "ggml-cpu-haswell.dll", "ggml-cpu-alderlake.dll",
    "ggml-cpu-cannonlake.dll", "ggml-cpu-cascadelake.dll",
    "ggml-cpu-icelake.dll", "ggml-cpu-skylakex.dll"
)
$LlamaFiles = @(
    "llama-server.exe", "llama-server-impl.dll", "llama-common.dll",
    "llama.dll", "mtmd.dll", "ggml.dll", "ggml-base.dll",
    "libomp140.x86_64.dll", "ggml-cpu-x64.dll", "ggml-cpu-sse42.dll",
    "ggml-cpu-piledriver.dll", "ggml-cpu-sandybridge.dll",
    "ggml-cpu-ivybridge.dll", "ggml-cpu-haswell.dll",
    "ggml-cpu-alderlake.dll", "ggml-cpu-cannonlake.dll",
    "ggml-cpu-cascadelake.dll", "ggml-cpu-cooperlake.dll",
    "ggml-cpu-icelake.dll", "ggml-cpu-skylakex.dll",
    "ggml-cpu-sapphirerapids.dll", "ggml-cpu-zen4.dll"
)
foreach ($File in $WhisperFiles) {
    Copy-Item -LiteralPath (Join-Path $WhisperExpanded "Release\$File") -Destination $WhisperTarget
}
foreach ($File in $LlamaFiles) {
    Copy-Item -LiteralPath (Join-Path $LlamaExpanded $File) -Destination $LlamaTarget
}

$VisualCppFiles = @("MSVCP140.dll", "VCRUNTIME140.dll", "VCRUNTIME140_1.dll")
foreach ($File in $VisualCppFiles) {
    $Source = Join-Path $env:WINDIR "System32\$File"
    Copy-Item -LiteralPath $Source -Destination $WhisperTarget
    Copy-Item -LiteralPath $Source -Destination $LlamaTarget
}
Copy-Item -LiteralPath (Join-Path $env:WINDIR "System32\VCOMP140.dll") -Destination $WhisperTarget

Reset-Directory $BuildRoot
if (Test-Path -LiteralPath $PackageRoot) {
    $null = Assert-WorkspacePath $PackageRoot
    Remove-Item -LiteralPath $PackageRoot -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $DistRoot | Out-Null

$PyInstallerArguments = @(
    "run", "--frozen", "pyinstaller", "--noconfirm", "--clean", "--onedir",
    "--console", "--noupx", "--name", "LocalFlow", "--contents-directory", ".",
    "--distpath", $DistRoot, "--workpath", $BuildRoot,
    "--specpath", $BuildRoot,
    "--add-data", "$(Join-Path $RepoRoot 'config.txt');.",
    "--add-data", "$(Join-Path $RepoRoot 'README.md');.",
    "--add-data", "$(Join-Path $RepoRoot 'THIRD_PARTY_NOTICES.md');.",
    "--add-data", "$(Join-Path $RepoRoot 'licenses');licenses",
    "--add-data", "$RuntimeRoot;runtime",
    (Join-Path $RepoRoot "main.py")
)
& uv @PyInstallerArguments
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

$PortAudioRoot = Join-Path $PackageRoot "_sounddevice_data\portaudio-binaries"
foreach ($File in @(
    "libportaudio.dylib",
    "libportaudio32bit-asio.dll",
    "libportaudio32bit.dll",
    "libportaudio64bit-asio.dll",
    "libportaudioarm64-asio.dll",
    "libportaudioarm64.dll"
)) {
    $UnneededBinary = Join-Path $PortAudioRoot $File
    if (Test-Path -LiteralPath $UnneededBinary) {
        Remove-Item -LiteralPath $UnneededBinary -Force
    }
}

# PyInstaller discovers copies of these DLLs through the native executables.
# Keep the required copies beside their executables under runtime instead.
foreach ($File in @(
    "ggml-base.dll",
    "ggml.dll",
    "libomp140.x86_64.dll",
    "llama-common.dll",
    "llama-server-impl.dll",
    "llama.dll",
    "mtmd.dll",
    "whisper.dll"
)) {
    $DuplicateRuntime = Join-Path $PackageRoot $File
    if (Test-Path -LiteralPath $DuplicateRuntime) {
        Remove-Item -LiteralPath $DuplicateRuntime -Force
    }
}

$PythonLicenseRoot = Join-Path $PackageRoot "licenses\python-packages"
& uv run --frozen python (Join-Path $PSScriptRoot "export_licenses.py") $PythonLicenseRoot
if ($LASTEXITCODE -ne 0) {
    throw "Dependency license export failed with exit code $LASTEXITCODE"
}

$RuntimeHashes = Get-ChildItem -Path (Join-Path $PackageRoot "runtime") -File -Recurse |
    Sort-Object FullName |
    ForEach-Object {
        [ordered]@{
            path = $_.FullName.Substring($PackageRoot.Length + 1).Replace("\", "/")
            sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        }
    }
$Manifest = [ordered]@{
    application = "LocalFlow"
    version = "0.1.0"
    platform = "windows-x64"
    whisper_cpp = "b4938"
    llama_cpp = "b10516"
    models_bundled = $false
    runtime_files = @($RuntimeHashes)
}
$Manifest | ConvertTo-Json -Depth 5 | Set-Content -Encoding UTF8 (Join-Path $PackageRoot "BUILD_MANIFEST.json")

& (Join-Path $PackageRoot "LocalFlow.exe") --version
if ($LASTEXITCODE -ne 0) {
    throw "Packaged LocalFlow.exe failed to start."
}
if (Test-Path -LiteralPath $PackageZip) {
    Remove-Item -LiteralPath $PackageZip -Force
}
Compress-Archive -Path (Join-Path $PackageRoot "*") -DestinationPath $PackageZip -CompressionLevel Optimal
$PackageHash = (Get-FileHash -LiteralPath $PackageZip -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Built $PackageZip"
Write-Host "SHA-256: $PackageHash"
