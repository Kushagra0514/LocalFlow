# Phase 7 model management, licensing, and packaging results

Date: 2026-08-28

## Outcome

LocalFlow now has a first-run model installer and a repeatable portable Windows
x64 build. The package includes Python and the pinned whisper.cpp and llama.cpp
CPU runtimes, but not the roughly 519 MiB of model weights. On first run, the
application downloads those weights directly from their official repositories
into `%LOCALAPPDATA%\LocalFlow\models`.

## Reproducibility and integrity

| Artifact | Pin | Verification |
| --- | --- | --- |
| whisper.cpp Windows x64 CPU runtime | `b4938` | release ZIP SHA-256 `c2a4b60edb11f7e11a9191ffb50929535527d4d91c9903dbe3e554583bbbc63d` |
| Whisper `base.en` Q5 | repository revision `5359861c739e955e79d9a303bcbc70fb988958b1` | SHA-256 `4baf70dd0d7c4247ba2b81fafd9c01005ac77c2f9ef064e00dcf195d0e2fdd2f` |
| llama.cpp Windows x64 CPU runtime | `b10516` | release ZIP SHA-256 `fbbbc55e0eb2e1b07f9dcb9488616c98ed47d9003b90e15e7c8c7812c4307cd3` |
| S1-mini by Superwhisper Q4_K_M | repository revision `34add00a48a2e5d24e5a4ee5405a99620a3a240c` | SHA-256 `3b41ebe2502cbd03e811d5d16b022f5ab551eda58d62597d152f89535003c634` |
| PyInstaller | `6.22.2` | exact version and wheel hashes locked in `uv.lock` |

Downloads go to a sibling `.part` file. LocalFlow checks the exact byte length
and SHA-256 digest before an atomic rename. A mismatch is deleted and rejected;
an interrupted partial is reported and restarted on the next run.

## Packaging

`packaging/build_windows.ps1` performs the following repeatable process:

1. obtains or reuses the two pinned native-runtime archives;
2. rejects either archive when its release checksum differs;
3. extracts only the CPU runtime files LocalFlow needs;
4. builds a PyInstaller one-folder application from the frozen dependency lock;
5. exports bundled Python-package licenses and adds the model/runtime notices;
6. records every packaged native-runtime file hash in `BUILD_MANIFEST.json`;
7. verifies that `LocalFlow.exe --version` launches; and
8. produces `dist/LocalFlow-windows-x64.zip`.

The package does not require Python, a compiler, Git, CMake, or other
development tools on the target computer.

Final package artifact, including the Phase 8 documentation:

- Path: `dist/LocalFlow-windows-x64.zip`
- Size: 43,712,434 bytes (41.7 MiB compressed)
- Extracted size: 105,510,809 bytes (100.6 MiB)
- SHA-256: `1186f506e0ae3fbb79fec631a74ca66ed34f9b6565371531125c14408ca42b05`

## Verification

- 32 automated application tests passed, including corrupt-download rejection,
  interrupted-download recovery, known-audio transcription, local cleanup, and
  offline normal operation.
- `LocalFlow.exe --verify-installation` verified both model checksums and
  launched the packaged whisper.cpp and llama.cpp executables.
- `packaging/test_package.ps1` extracted the ZIP into an isolated install
  directory, used an isolated model cache, ran installation verification and a
  real fixed-audio transcription/cleanup smoke test, then removed both locations
  and confirmed no test files remained.
- Archive inspection confirmed that neither `.bin` nor `.gguf` model weights
  are accidentally bundled, while the required licenses and notices are.

The isolated test exercises the portable install and removal flow, but it is
not a substitute for a separate clean Windows account. That checklist item
remains open for release validation on another account or Windows Sandbox.

## Licenses and notices

The package ships the upstream licenses for whisper.cpp, llama.cpp, the OpenAI
Whisper model, S1-mini by Superwhisper, PortAudio, CPython, PyInstaller, and the
included Python packages. It also ships the upstream S1-mini by Superwhisper
NOTICE and a Microsoft Visual C++ runtime redistribution notice. The complete
inventory is in `THIRD_PARTY_NOTICES.md`.
