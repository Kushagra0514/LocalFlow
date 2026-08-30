param(
    [string]$Executable = "",
    [string]$ModelDirectory = "",
    [string]$Sample = "",
    [int]$Runs = 4
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
if (-not $Executable) {
    $Executable = Join-Path $RepoRoot "dist\LocalFlow\LocalFlow.exe"
}
if (-not $ModelDirectory) {
    $ModelDirectory = Join-Path $RepoRoot ".local\phase1"
}
if (-not $Sample) {
    $Sample = Join-Path $RepoRoot ".local\phase1\samples\jfk.wav"
}
if ($Runs -lt 1) {
    throw "Runs must be at least 1."
}

function Read-Measurement([string[]]$Output, [string]$Name) {
    $Pattern = "^\[Smoke $([Regex]::Escape($Name))\]: ([0-9.]+)$"
    foreach ($Line in $Output) {
        if ($Line -match $Pattern) {
            return [double]$Matches[1]
        }
    }
    throw "Smoke-test output did not contain '$Name'."
}

$OldDataDirectory = $env:LOCALFLOW_DATA_DIR
try {
    $env:LOCALFLOW_DATA_DIR = $ModelDirectory
    $Results = for ($Run = 1; $Run -le $Runs; $Run++) {
        $Timer = [Diagnostics.Stopwatch]::StartNew()
        $Output = @(& $Executable --smoke-test $Sample 2>&1 | ForEach-Object { "$_" })
        $ExitCode = $LASTEXITCODE
        $Timer.Stop()
        if ($ExitCode -ne 0) {
            throw "Release smoke test failed with exit code ${ExitCode}:`n$($Output -join "`n")"
        }
        [pscustomobject]@{
            Run = $Run
            Cache = if ($Run -eq 1) { "first" } else { "repeat" }
            ProcessSeconds = [Math]::Round($Timer.Elapsed.TotalSeconds, 3)
            WhisperSeconds = Read-Measurement $Output "Whisper Seconds"
            PipelineSeconds = Read-Measurement $Output "Pipeline Seconds"
            PeakMiB = Read-Measurement $Output "Peak MiB"
        }
    }
    $Results | Format-Table -AutoSize
}
finally {
    $env:LOCALFLOW_DATA_DIR = $OldDataDirectory
}
