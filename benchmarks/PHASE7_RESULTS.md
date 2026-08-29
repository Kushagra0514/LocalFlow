# Phase 7 model management, licensing, and packaging results

Date: 2026-08-28

## Outcome

LocalFlow now has first-run model management, a repeatable portable Windows x64
build, and a one-click per-user Windows installer. The installer includes the
application, Python, and the pinned whisper.cpp and llama.cpp CPU runtimes, but
not the roughly 519 MiB of model weights. On first run, the application
downloads those weights directly from their official repositories into
`%LOCALAPPDATA%\LocalFlow\models`.

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
an interrupted partial is reported and restarted on the next run. Version 0.1.1
uses the pinned certifi public roots together with certificates managed by
Windows for verified HTTPS model downloads.

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

`packaging/build_installer.ps1` runs that application build and compiles
`packaging/LocalFlow.iss` with Inno Setup. The resulting current-user installer
requires no administrator access, creates Start Menu and optional desktop
shortcuts, preserves an existing `config.txt` during upgrades, registers a
Windows uninstaller, and optionally launches LocalFlow after installation.

Artifacts from the installer build:

- Path: `dist/LocalFlow-windows-x64.zip`
- Size: 43,847,025 bytes (41.8 MiB compressed)
- SHA-256: `3d8c52edc5c39630b7b9b65a3c5373edd4d93e8377b46ab86929442a0c4b654c`
- Installer path: `dist/LocalFlow-Setup.exe`
- Installer size: 27,943,378 bytes (26.6 MiB)
- Installer SHA-256: `1b2c74395127c9ef2767465948f42105fd1370d3cfc6690882c0488d990624b2`
- Code-signing status: unsigned

## Verification

- 31 automated application tests passed and 3 optional model-fixture tests were
  skipped, including coverage for corrupt-download rejection,
  interrupted-download recovery, combined bundled/Windows certificate trust,
  startup-error visibility, local cleanup fallback, and offline safeguards.
- The exact packaged executable downloaded both models into an empty isolated
  data directory, verified both pinned checksums, and removed the test copies.
- `LocalFlow.exe --verify-installation` verified both model checksums and
  launched the packaged whisper.cpp and llama.cpp executables.
- `packaging/test_package.ps1` extracted the ZIP into an isolated install
  directory, used an isolated model cache, ran installation verification and a
  real fixed-audio transcription/cleanup smoke test, then removed both locations
  and confirmed no test files remained.
- Archive inspection confirmed that neither `.bin` nor `.gguf` model weights
  are accidentally bundled, while the required licenses and notices are.
- `packaging/test_installer.ps1` silently installed the complete application to
  an isolated directory, launched the installed executable, ran the registered
  uninstaller, and confirmed that cleanup completed.

The isolated test exercises the portable install and removal flow, but it is
not a substitute for a separate clean Windows account. That checklist item
remains open for release validation on another account or Windows Sandbox.

## Licenses and notices

The package ships the upstream licenses for whisper.cpp, llama.cpp, the OpenAI
Whisper model, S1-mini by Superwhisper, PortAudio, CPython, PyInstaller, and the
included Python packages. It also ships the upstream S1-mini by Superwhisper
NOTICE and a Microsoft Visual C++ runtime redistribution notice. The complete
inventory is in `THIRD_PARTY_NOTICES.md`.
