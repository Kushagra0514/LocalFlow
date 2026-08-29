# Phase 8 documentation and release-verification results

Date: 2026-08-28

## Outcome

LocalFlow now includes user documentation for installation, use,
configuration, privacy, supported hardware, and troubleshooting. It explicitly
documents combination hotkeys, opt-in automatic paste, English-only S1-mini by
Superwhisper cleanup, and the limits of the available hardware measurements.

The packaged application also exposes a fixed-audio release smoke test. It runs
the real whisper.cpp-to-S1-mini pipeline and samples the combined working set of
the packaged LocalFlow controller and whichever native inference process is
active. The package test executes this check from a newly extracted isolated
installation and removes the isolated installation and model cache afterward.

## Test system and method

- CPU: Intel Core Ultra 7 155H
- Logical processors: 22
- Inference thread limit: 4
- OS: Windows 10.0.26200, x64
- Dedicated GPU acceleration: not used
- Package form: PyInstaller one-folder Windows x64 executable
- Final package: 43,712,434 bytes (41.7 MiB compressed)
- Package SHA-256: `1186f506e0ae3fbb79fec631a74ca66ed34f9b6565371531125c14408ca42b05`
- Fixed audio: 11-second whisper.cpp `jfk.wav`, 16 kHz mono PCM
- Audio SHA-256: `59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e`
- Memory sampling interval: 25 ms

`benchmarks/measure_release.ps1` started a new packaged `LocalFlow.exe` for each
run. The reported process time includes executable startup, configuration and
model verification, transcription, cleanup, and orderly exit. The pipeline
time begins immediately before transcription. Each dictation starts separate
Whisper and S1 native processes sequentially, so native model startup is
included in every pipeline value.

The first row is the first measured process in this sequence. Repeat rows
benefit from whatever filesystem caching Windows retained. This is not a claim
of a machine-wide cold boot, and “repeat” does not mean that either model stays
resident.

## Packaged measurements

| Run | Cache condition | Complete process | Whisper | S1 cleanup | Pipeline | Peak tree working set |
| ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1 | first measured | 4.13 s | 1.28 s | 1.81 s | 3.09 s | 939.5 MiB |
| 2 | repeat | 4.18 s | 1.23 s | 2.04 s | 3.27 s | 938.7 MiB |
| 3 | repeat | 3.98 s | 1.26 s | 1.79 s | 3.05 s | 939.9 MiB |
| 4 | repeat | 4.26 s | 1.46 s | 1.89 s | 3.35 s | 939.0 MiB |

The highest observed complete-process-tree working set was **939.9 MiB**, below
the 1 GiB release target by about 84 MiB. It is close enough to the limit that
the exact baseline model/runtime pins and sequential process design should not
be changed without repeating this measurement.

The fixed sample produced:

> And so my fellow Americans, ask not what your country can do for you, ask
> what you can do for your country.

S1-mini returned the same already-clean sentence. An additional deterministic
automated cleanup fixture verifies filler removal and correction.

## Automated and package verification

- 32 automated tests passed.
- The suite covers configuration parsing, state transitions, no microphone,
  missing runtimes, missing Whisper and S1 models, invalid hotkeys, empty
  speech, cleanup fallback, clipboard failure, and shutdown during processing.
- A real fixed-audio test rejects any non-loopback network connection while
  running transcription and cleanup.
- `packaging/test_package.ps1` extracted the ZIP to an isolated path, copied the
  verified pinned models into an isolated cache, ran installation verification
  and the real fixed-audio smoke test, and confirmed complete removal.
- The final-package smoke test returned exit code zero, the expected transcript,
  and a combined peak of 939.5 MiB in that isolated run.
- Archive inspection found no bundled `.bin` or `.gguf` model weights and found
  40 license files.

## Release-criteria status

| Criterion | Status | Evidence or remaining work |
| --- | --- | --- |
| Windows x64 CPU-only, no dedicated GPU | Pass on measured system | Package and both native runtimes ran without GPU acceleration. |
| No cloud account or API key | Pass | No credential dependency remains; only first-run model download requires external networking. |
| Less than 1 GiB peak for the full process tree | Pass on measured system | Maximum observed packaged peak was 939.9 MiB. |
| Raw transcript survives cleanup failure | Pass | Automated fallback test verifies the raw result is copied. |
| Clipboard reliable; automatic paste opt-in | Pass | Copy/paste behavior and shutdown suppression are automated. |
| Clean install, model download, dictation, shutdown | Partial | Isolated portable install/removal and all functional paths pass. A separate clean Windows account or Windows Sandbox test remains open. |

This modern development computer is not evidence that all ten-year-old
hardware will achieve the same latency or remain below the same working-set
peak. A representative low-resource computer and a genuinely clean Windows
account remain the two release-validation gaps.
