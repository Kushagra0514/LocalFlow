# LocalFlow

LocalFlow is a fully local, CPU-first push-to-talk dictation tool for 64-bit
Windows. It transcribes English with whisper.cpp and cleans the transcript with
S1-mini by Superwhisper. After the two model files have been downloaded,
dictation needs no cloud service, account, API key, or dedicated GPU.

## Supported hardware

The supported baseline is Windows 10 or 11 on a 64-bit x86 CPU, using CPU-only
inference. LocalFlow limits each inference engine to at most four logical CPU
threads so that it remains usable on lower-powered systems.

Allow roughly 750 MiB of disk space for the extracted application and its
models, plus about 1 GiB of free working memory beyond Windows and other open
applications. The current measurements were made on a modern Intel Core Ultra
7 155H. Hardware from the last ten years is a design target, not a promise:
older CPUs may take substantially longer and still need representative testing.

LocalFlow is English-only in this release. Both the `base.en` transcription
model and the S1-mini by Superwhisper cleanup configuration target English.

## Install the Windows package

1. Download `LocalFlow-windows-x64.zip` and extract the whole folder.
2. Run `LocalFlow.exe` from the extracted folder. Do not run it inside the ZIP.
3. Keep the terminal open while LocalFlow downloads and verifies the two model
   files on first run. The one-time download is about 519 MiB.
4. Wait for the `Ready!` message.

The package includes Python and the pinned whisper.cpp and llama.cpp CPU
runtimes. Python, Git, CMake, a compiler, and development tools are not needed.

Models are stored outside the application folder in
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
4. Wait while LocalFlow transcribes and cleans the text. Only one recording can
   be processed at a time.
5. Paste from the clipboard with `Ctrl+V`, unless automatic paste is enabled.

A recording is limited to 60 seconds. If S1-mini cleanup fails or is
unavailable, LocalFlow keeps the successful raw Whisper transcript and copies
that instead. Empty or silent recordings do not invoke cleanup.

Keep the terminal window open. Press `Ctrl+C` there for a clean shutdown.

## Configuration

Edit `config.txt` beside `LocalFlow.exe` while LocalFlow is stopped, then start
it again. The default is:

```text
HOTKEY=f23
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

Every successful result is copied to the clipboard. With the safer default
`AUTO_PASTE=false`, LocalFlow never sends a paste keystroke. With
`AUTO_PASTE=true`, it sends `Ctrl+V` to whichever application has focus when
processing finishes. That may not be the application that was focused when
recording began, so leave this disabled if focus can change unexpectedly.

## Privacy and network behavior

- The only required external network activity is the first-run download of the
  two pinned models from their official Hugging Face repositories.
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

Release measurements use the packaged executable, four CPU threads, and the
fixed 11-second JFK audio sample on an Intel Core Ultra 7 155H:

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
checksum is rejected rather than loaded.

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

Delete the extracted LocalFlow folder. To remove the downloaded models too,
delete `%LOCALAPPDATA%\LocalFlow`. LocalFlow does not install a service or write
configuration to the system registry.

Third-party versions, checksums, licenses, and notices are listed in
`THIRD_PARTY_NOTICES.md` and the `licenses` folder.

## Build and verify from source

Development uses the exact dependency versions in `uv.lock`:

```powershell
$env:UV_CACHE_DIR = ".local\packaging\uv-cache"
uv sync --frozen
uv run --frozen python -m unittest discover -s tests -v
.\packaging\build_windows.ps1
.\packaging\test_package.ps1
.\benchmarks\measure_release.ps1
```
