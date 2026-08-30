# LocalFlow

LocalFlow is a fully local, CPU-first push-to-talk dictation tool for 64-bit
Windows. It transcribes English with whisper.cpp and can optionally clean the
transcript with S1-mini by Superwhisper. Cleanup is disabled by default, so
normal dictation requires only the Whisper model and no cloud service, account,
API key, or dedicated GPU.

## Supported hardware

The supported baseline is Windows 10 or 11 on a 64-bit x86 CPU, using CPU-only
inference. LocalFlow limits each inference engine to at most four logical CPU
threads so that it remains usable on lower-powered systems.

Allow roughly 160 MiB of disk space for the extracted application and required
Whisper model. Enabling the current optional S1-mini cleanup adds about 462 MiB
of model data. The current measurements were made on a modern Intel Core Ultra
7 155H. Hardware from the last ten years is a design target, not a promise:
older CPUs may take substantially longer and still need representative testing.

LocalFlow is English-only in this release. Both the `base.en` transcription
model and the S1-mini by Superwhisper cleanup configuration target English.

## Install LocalFlow

1. Open the [LocalFlow releases page](https://github.com/Kushagra0514/LocalFlow/releases).
2. Download `LocalFlow-Setup.exe` from the newest release.
3. Double-click it, complete the installer, and open LocalFlow from the Start
   Menu.
4. Keep the terminal open while LocalFlow downloads and verifies the Whisper
   model on first run. The default one-time download is about 57 MiB. If local
   cleanup is enabled, LocalFlow also downloads the roughly 462 MiB S1 model.
5. Wait for the `Ready!` message.

The installer includes LocalFlow, Python, and the pinned whisper.cpp and
llama.cpp CPU runtimes. Python, Git, CMake, a compiler, and development tools
are not needed on the user's computer. LocalFlow is installed only for the
current Windows user, so the installer does not request administrator access.

The current installer is not code-signed, so Windows may identify its publisher
as unknown. Download it only from the official LocalFlow release page and
compare its SHA-256 with the value in that release's notes before running it.

Model files are stored outside the application folder in
`%LOCALAPPDATA%\LocalFlow\models`. Downloads use a `.part` file and are checked
against pinned sizes and SHA-256 digests before installation. If a download is
interrupted, start LocalFlow again; it discards the partial file and restarts
that model.

These optional commands install models or verify an existing installation
without starting the hotkey listener:

```powershell
.\LocalFlow.exe --setup-models
.\LocalFlow.exe --verify-installation
.\LocalFlow.exe --version
```

## Use LocalFlow

1. Put the cursor where you eventually want the text.
2. Hold the configured hotkey and wait for `Recording started`.
3. Speak for at least 0.3 seconds, then release the hotkey.
4. Wait while LocalFlow transcribes and, when enabled, cleans the text. Only one
   recording can be processed at a time.
5. Paste from the clipboard with `Ctrl+V`, unless automatic paste is enabled.

A recording is limited to 60 seconds. If S1-mini cleanup fails or is
unavailable, LocalFlow keeps the successful raw Whisper transcript and copies
that instead. Empty or silent recordings do not invoke cleanup.

Keep the terminal window open. Press `Ctrl+C` there for a clean shutdown.

## Configuration

Edit `config.txt` beside `LocalFlow.exe` while LocalFlow is stopped, then start
it again. Installer upgrades preserve this file. The default is:

```text
HOTKEY=f23
CLEANUP=false
AUTO_PASTE=false
```

`HOTKEY` accepts a single key or a modifier combination. For combinations,
list every modifier first and one ordinary trigger key last:

```text
HOTKEY=f23
HOTKEY=f12
HOTKEY=ctrl
HOTKEY=right shift
HOTKEY=ctrl+shift+space
```

`f23` keeps the Windows Copilot key behavior working on keyboards that emit
F23. For `ctrl+shift+space`, LocalFlow starts recording when Space is pressed
while Ctrl and Shift are held. Releasing Space, or releasing a required
modifier early, stops the recording. Choose a combination that does not
conflict with shortcuts in your other applications.

With `CLEANUP=true`, LocalFlow processes each raw Whisper transcript through
S1-mini by Superwhisper. With `CLEANUP=false`, it skips S1-mini and copies the
raw Whisper transcript directly. When cleanup is disabled, the S1-mini model
and llama.cpp runtime are not required during normal use.

Every successful result is copied to the clipboard. With the safer default
`AUTO_PASTE=false`, LocalFlow never sends a paste keystroke. With
`AUTO_PASTE=true`, it sends `Ctrl+V` to whichever application has focus when
processing finishes. That may not be the application that was focused when
recording began, so leave this disabled if focus can change unexpectedly.

## Privacy and network behavior

- The only required external network activity is the first-run download of the
  pinned Whisper model from its official Hugging Face repository. Enabling the
  current local cleanup also downloads the pinned S1 model once.
- Once valid models are present, normal transcription and cleanup make no
  external network request. S1-mini communicates with a temporary llama.cpp
  server bound only to `127.0.0.1` on the same computer.
- Recorded audio is written to a temporary WAV file for whisper.cpp and removed
  immediately after that transcription attempt.
- LocalFlow does not create transcript history or log files. The raw and final
  text are shown in the terminal, and the final text remains on the Windows
  clipboard until another application replaces it.
- Automatic paste is opt-in and targets the application focused when processing
  completes.

## Observed performance

These published v0.1.1 measurements used the `base.en` Q5 model, four CPU
threads, and the fixed 11-second JFK audio sample on an Intel Core Ultra 7
155H. They measured the optional local S1 cleanup path:

| Measurement | First measured run | Three repeat runs |
| --- | ---: | ---: |
| Complete new LocalFlow process | 4.13 s | 3.98–4.26 s |
| Whisper transcription | 1.28 s | 1.23–1.46 s |
| S1-mini cleanup | 1.81 s | 1.79–2.04 s |
| Whisper-to-cleaned-text pipeline | 3.09 s | 3.05–3.35 s |
| Peak complete-process-tree working set | 939.5 MiB | 938.7–939.9 MiB |

Every dictation starts new native Whisper and S1 processes, so the model-load
cost is included in every pipeline value. “Repeat” means a new LocalFlow process
with a likely warm Windows filesystem cache, not a permanently resident model.
The monitor sampled the packaged controller and its active native child every
25 ms. Full details are in `benchmarks/PHASE8_RESULTS.md`.

Latency depends on CPU generation, current load, power mode, storage, and
filesystem caching. Do not assume that an older computer will match the
development system.

## Troubleshooting

**A model download stopped or failed verification.** Start LocalFlow again. It
reports and removes interrupted `.part` files. A file with the wrong size or
checksum is rejected rather than loaded. HTTPS downloads trust both LocalFlow's
bundled current public certificate roots and certificates managed by Windows.

**LocalFlow reports a missing model.** Run `LocalFlow.exe --setup-models` with
an internet connection. If the model directory was manually changed or
deleted, let setup recreate it.

**LocalFlow reports a missing runtime or DLL.** Extract the entire ZIP again;
do not copy only `LocalFlow.exe`. If Windows specifically reports a missing
`MSVCP140.dll`, `VCRUNTIME140.dll`, or `VCOMP140.dll`, install Microsoft's
current [Visual C++ x64 Redistributable](https://aka.ms/vs/17/release/vc_redist.x64.exe).

**The microphone will not open.** Confirm that a working default input device
is selected and that Windows microphone privacy settings allow desktop apps to
use it. Close other software that has exclusive control of the device.

**No speech is detected.** Hold the hotkey for at least 0.3 seconds, speak
closer to the selected microphone, and check its input level in Windows.

**The hotkey is rejected or does nothing.** Check the spelling in `config.txt`,
put modifiers first, and use one non-modifier key last. Try `f12` to rule out a
shortcut conflict. Restart LocalFlow after editing the file.

**LocalFlow says `Still processing`.** Wait for the next `Ready!` message.
Overlapping recordings are intentionally blocked.

**Cleanup failed.** The raw Whisper transcript is still copied. Verify the
installation to check the S1-mini model and llama.cpp runtime.

**Automatic paste went to the wrong application.** Set `AUTO_PASTE=false` and
paste manually. Automatic paste always uses the focus at completion time.

**Dictation is slow.** Keep the computer connected to power, close CPU-heavy
applications, and compare a repeat attempt. Older hardware is expected to be
slower than the published development-system measurement.

## Remove LocalFlow

Open Windows **Settings → Apps → Installed apps**, find LocalFlow, and choose
**Uninstall**. To remove the downloaded models too, delete
`%LOCALAPPDATA%\LocalFlow`. LocalFlow does not install a background service.

Third-party versions, checksums, licenses, and notices are listed in
`THIRD_PARTY_NOTICES.md` and the `licenses` folder.

## Build and verify from source

Development uses the exact dependency versions in `uv.lock`:

```powershell
$env:UV_CACHE_DIR = ".local\packaging\uv-cache"
uv sync --frozen
uv run --frozen python -m unittest discover -s tests -v
.\packaging\build_installer.ps1
.\packaging\test_package.ps1
.\packaging\test_installer.ps1
.\benchmarks\measure_release.ps1
```

`build_installer.ps1` requires [Inno Setup](https://jrsoftware.org/isdl.php) on
the development computer. It first creates the complete application bundle and
then writes the single user-facing installer to `dist\LocalFlow-Setup.exe`.
