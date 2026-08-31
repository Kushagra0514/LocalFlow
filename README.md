# LocalFlow

LocalFlow is a local-first, CPU-first push-to-talk dictation tool for 64-bit
Windows. It transcribes English locally with whisper.cpp and copies the result
to the clipboard. The default configuration requires no cloud service, account,
API key, or dedicated GPU. Optional transcript cleanup can use a user-provided
Groq API key.

## Supported hardware

The supported baseline is Windows 10 or 11 on a 64-bit x86 CPU, using CPU-only
inference. LocalFlow limits each inference engine to at most four logical CPU
threads so that it remains usable on lower-powered systems.

Allow roughly 160 MiB of disk space for the extracted application and required
Whisper model. The current measurements were made on a modern Intel Core Ultra
7 155H. Hardware from the last ten years is a design target, not a promise:
older CPUs may take substantially longer and still need representative testing.

LocalFlow is English-only in this release and uses the `base.en` transcription
model.

## Install LocalFlow

1. Open the [LocalFlow releases page](https://github.com/Kushagra0514/LocalFlow/releases).
2. Download `LocalFlow-Setup.exe` from the newest release.
3. Double-click it, complete the installer, and open LocalFlow from the Start
   Menu.
4. Keep the terminal open while LocalFlow downloads and verifies the Whisper
   model on first run. The one-time download is about 57 MiB.
5. Wait for the `Ready!` message.

The installer includes LocalFlow, Python, and the pinned whisper.cpp CPU
runtime. Python, Git, CMake, a compiler, and development tools are not needed
on the user's computer. LocalFlow is installed only for the current Windows
user, so the installer does not request administrator access.

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
.\LocalFlow.exe --config-path
.\LocalFlow.exe --check-config
.\LocalFlow.exe --version
```

## Use LocalFlow

1. Put the cursor where you eventually want the text.
2. Hold the configured hotkey and wait for `Recording started`.
3. Speak for at least 0.3 seconds, then release the hotkey.
4. Wait while LocalFlow transcribes the text. Only one recording can be
   processed at a time.
5. Paste from the clipboard with `Ctrl+V`, unless automatic paste is enabled.

A recording is limited to 60 seconds. Empty or silent recordings do not copy
text.

Keep the terminal window open. Press `Ctrl+C` there for a clean shutdown.

## Configuration

The one live configuration is `%LOCALAPPDATA%\LocalFlow\config.ini`. LocalFlow
prints this path at ordinary startup. Run `LocalFlow.exe --config-path` to print
only the path or `LocalFlow.exe --check-config` to validate the file without
starting the hotkey listener.

Edit `config.ini` while LocalFlow is stopped, then start it again. The safe
defaults are:

```ini
[hotkeys]
dictation = f23
command = ctrl+shift+.

[output]
auto_paste = false

[cleanup]
enabled = false

[commands]
enabled = false

[ai]
provider = groq
model = openai/gpt-oss-20b
timeout_seconds = 15
```

The `dictation` and `command` hotkeys must be different. Each accepts a single
key or a modifier combination. For combinations, list every modifier first and
one ordinary trigger key last:

```ini
dictation = f23
dictation = f12
dictation = ctrl
dictation = right shift
dictation = ctrl+shift+space
```

`f23` keeps the Windows Copilot key behavior working on keyboards that emit
F23. For `ctrl+shift+space`, LocalFlow starts recording when Space is pressed
while Ctrl and Shift are held. Releasing Space, or releasing a required
modifier early, stops the recording. Choose a combination that does not
conflict with shortcuts in your other applications.

Every successful result is copied to the clipboard. With the safer default
`auto_paste = false`, LocalFlow never sends a paste keystroke. With
`auto_paste = true`, it sends `Ctrl+V` to whichever application has focus when
processing finishes. That may not be the application that was focused when
recording began, so leave this disabled if focus can change unexpectedly.

On first run, LocalFlow imports only `HOTKEY` and `AUTO_PASTE` from an older
`config.txt` beside the executable. It leaves that TXT file untouched for
rollback. A legacy `CLEANUP=true` is deliberately ignored and cloud cleanup is
initialized to false, so an upgrade cannot silently enable transcript upload.
API keys remain environment variables and cannot be stored in this INI.

With `cleanup.enabled = false`, LocalFlow publishes the raw Whisper transcript
and never reads an API key or contacts a cloud provider. To opt into cleanup,
store a Groq key in the current Windows user's environment and then enable it:

```powershell
[Environment]::SetEnvironmentVariable("GROQ_API_KEY", "your-key", "User")
```

Restart LocalFlow after setting the variable, then set `cleanup.enabled = true`.
Only transcript text is sent to Groq; recorded audio remains local. The cleanup
request asks for English punctuation, capitalization, filler/false-start
removal, and clear recognition corrections without changing meaning, names, or
numbers. If the key is missing or any cleanup request fails, LocalFlow reports
the category of failure and copies the successful raw Whisper transcript.

## Privacy and network behavior

- The only required external network activity is the first-run download of the
  pinned Whisper model from its official Hugging Face repository.
- Once that valid model is present, normal transcription makes no external
  network request while cleanup remains disabled.
- When cloud cleanup is explicitly enabled, LocalFlow sends the transcript text
  to the configured Groq model. It never sends microphone audio to Groq.
- Recorded audio is written to a temporary WAV file for whisper.cpp and removed
  immediately after that transcription attempt.
- LocalFlow does not create transcript history or log files. The text being
  published is shown in the terminal: cleaned text after successful cleanup or
  the raw Whisper transcript after fallback. Provider error bodies and request
  contents are not printed. The published text remains on the Windows clipboard
  until another application replaces it.
- Automatic paste is opt-in and targets the application focused when processing
  completes.

## Observed performance

These v0.2 measurements used the `base.en` Q5 model, four CPU
threads, and the fixed 11-second JFK audio sample on an Intel Core Ultra 7
155H:

| Measurement | First measured run | Three repeat runs |
| --- | ---: | ---: |
| Complete new LocalFlow process | 4.79 s | 3.80–5.08 s |
| Whisper transcription | 3.60 s | 2.61–3.72 s |
| Raw-transcript pipeline | 3.60 s | 2.61–3.72 s |
| Peak complete-process-tree working set | 264.0 MiB | 264.2–265.2 MiB |

Every dictation starts a new native Whisper process, so model-load cost is
included. The monitor sampled the packaged controller and its active native
child every 25 ms.

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

**The configuration is rejected.** Run `LocalFlow.exe --check-config` for the
specific section and key. Unknown settings are rejected. For hotkeys, put
modifiers first, use one non-modifier key last, and ensure the dictation and
command bindings differ. Try `f12` to rule out a shortcut conflict.

**Cloud cleanup is unavailable.** Confirm `GROQ_API_KEY` is set for the current
Windows user, restart LocalFlow, and check that the configured Groq model is
available to your account. LocalFlow continues with raw local transcripts while
cleanup is unavailable.

**LocalFlow says `Still processing`.** Wait for the next `Ready!` message.
Overlapping recordings are intentionally blocked.

**Automatic paste went to the wrong application.** Set `auto_paste = false` and
paste manually. Automatic paste always uses the focus at completion time.

**Dictation is slow.** Keep the computer connected to power, close CPU-heavy
applications, and compare a repeat attempt. Older hardware is expected to be
slower than the published development-system measurement.

## Remove LocalFlow

Open Windows **Settings → Apps → Installed apps**, find LocalFlow, and choose
**Uninstall**. To remove the downloaded Whisper model too, delete
`%LOCALAPPDATA%\LocalFlow`. LocalFlow does not install a background service.

An upgrade from an older build removes the obsolete llama.cpp files from the
application installation, but intentionally leaves user model data alone. If
it exists, the retired S1 model can be removed manually at exactly:

```text
%LOCALAPPDATA%\LocalFlow\models\s1-mini-q4_k_m.gguf
```

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

### Adding an OpenAI-compatible provider

Cloud transport is isolated in `localflow/cloud.py`. To support another trusted
OpenAI-compatible service, add one `Provider` entry containing its fixed base
URL, API-key environment-variable name, default model, and required headers.
The configuration validator reads that registry, so recording, Whisper,
output, tools, and application state do not change.

Run the reusable provider contract tests against a local fake server before
enabling the provider. They must prove the service accepts the normalized
request and returns normalized text or one tool call. Never add a user-defined
base URL. If a future provider cannot satisfy this Chat Completions contract,
give it a small separate adapter behind the same `CompletionRequest` and
`CompletionResponse` boundary.
