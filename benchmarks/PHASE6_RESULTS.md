# Phase 6 local-data and offline-operation results

Date: 2026-08-28

## Outcome

LocalFlow requires no API key and completes the real Whisper-to-S1 pipeline
without an external network connection. The only TCP traffic is between the
Python controller and the temporary llama.cpp server bound to `127.0.0.1`.

Secrets, downloaded models and runtimes, temporary recording outputs, and logs
now have explicit Git ignore coverage. Groq, Faster-Whisper, CTranslate2, and
dotenv remain absent from application code, declared dependencies, the
lockfile, and the installed environment.

## Git protection

`.gitignore` now covers:

- `.env` and `.env.*` secret or environment files;
- the complete `.local/` artifact area;
- `models/` and `runtimes/` directories;
- GGUF and `ggml-*.bin` model files;
- downloaded `whisper-cli.exe` and `llama-*.exe` tools;
- `localflow-*` temporary directories plus the known `recording.wav` and
  `transcript.txt` temporary names; and
- `logs/` and `*.log` output.

`git check-ignore --no-index` matched every representative path. The real
`.env` now appears as ignored rather than untracked, and the downloaded
`.local/` tree remains ignored. `.env` is not tracked and has no entry in the
available local Git history.

Temporary audio is written inside Python's `TemporaryDirectory` and is removed
when transcription succeeds, fails, or times out. The ignore entries provide
a second layer if a temporary file is ever placed in the repository manually.

## Offline verification

Three independent checks were used:

1. Source inspection found only two runtime URLs. Both are hard-coded
   `http://127.0.0.1` health and completion endpoints for the local llama.cpp
   process.
2. A real fixed-audio Whisper-to-S1 integration test replaced Python's socket
   connector with a guard that raises on any destination other than loopback.
   The pipeline passed and produced the expected transcript and cleanup.
3. A process-level TCP audit sampled the Python controller and every newly
   started `whisper-cli` and `llama-server` process during three complete runs.
   It observed only `127.0.0.1` llama.cpp listeners and loopback connections;
   no external connection was observed.

The integration check also passed after removing `GROQ_API_KEY` from the test
process environment. `uv sync --offline` and `uv lock --check` both succeed.
This demonstrates normal inference with external networking unavailable while
retaining Windows loopback, which remains available when a network adapter is
disconnected.

## Verification

All 26 tests pass. The new offline test runs both real local models and rejects
any non-loopback Python connection. Native-process traffic was verified by the
separate process-level audit described above.

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Conditional key rotation

The existing `.env` was not opened or modified. Local Git provides no evidence
that it was ever committed, but it cannot show whether the key was copied,
messaged, screenshotted, or otherwise shared outside the repository.

If that key has ever been shared, it must be revoked and replaced from the
Groq account that issued it. LocalFlow will not need the replacement because
the application no longer reads `.env` or uses Groq. If the file serves no
other local project, it can also be deleted after the owner confirms that it
is no longer needed.
