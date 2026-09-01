# Phase 2 whisper.cpp integration results

> Historical v0.1 record. References to local S1/llama.cpp describe the retired
> architecture and are not v0.2 performance claims.

Date: 2026-08-28

## Outcome

LocalFlow now records 16 kHz mono float audio, converts it to a temporary
16-bit PCM WAV file, and transcribes it with the pinned whisper.cpp executable
and `base.en` Q5 model. Faster-Whisper and CTranslate2 are no longer imported,
declared, locked, or installed in the project environment.

Groq cleanup remains unchanged for Phase 3.

## Implementation

- Runtime: `.local/phase1/whisper/Release/whisper-cli.exe`
- Model: `.local/phase1/models/ggml-base.en-q5_1.bin`
- Language: English
- CPU thread limit: `min(4, available logical processors)`
- Audio passed to Whisper: 16,000 Hz, mono, signed 16-bit PCM WAV
- Runtime lifecycle: one whisper.cpp process per recording
- Temporary audio and transcript files: automatically removed after each run
- Process timeout: 120 seconds

The one-shot lifecycle is intentional. Phase 1 showed that sequential model
processes can meet the complete-application 1 GiB target, while keeping both
the Whisper and S1-mini servers resident alongside the current Python
controller cannot.

## Functional checks

Five checks pass using Python's standard `unittest` runner:

1. The fixed 11-second JFK sample produces the expected transcript.
2. A missing whisper.cpp executable raises a clear installation error.
3. Digital silence returns an empty transcript without starting whisper.cpp.
4. An empty/no-speech result does not invoke transcript cleanup.
5. A transcription failure is reported and the application prints its ready
   state again.

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Measurement

Test system and artifact pins are recorded in
[`PHASE1_RESULTS.md`](PHASE1_RESULTS.md).

- Fixed sample: 11 seconds, 16 kHz mono
- Application-path runs: 3,492.2 ms, 3,819.3 ms, and 3,435.6 ms
- Median application-path latency: 3,492.2 ms
- Same-session direct whisper.cpp timing: 3,146.1 ms
- Observed complete Python-plus-whisper process-tree peak: 280.3 MiB

The same binary completed much faster during the earlier Phase 1 measurements,
so the absolute latency is sensitive to current machine load and power state.
The application adds roughly 0.35 seconds over the same-session direct command,
primarily for process control and temporary file handling. Memory remains well
below the Phase 1 budget and leaves room for the sequential S1-mini cleanup
stage.

## Dependency result

Regenerating the lockfile removed Faster-Whisper and its unused transitive
packages, including CTranslate2, ONNX Runtime, tokenizers, Hugging Face Hub,
and PyAV. `uv lock --check` succeeds after the change.

## Known limitation

No-speech detection currently uses a simple RMS threshold of `0.002` before
starting Whisper. This prevents the observed digital-silence hallucination,
but it is not a full voice-activity detector. If real noisy-room testing shows
false activations, whisper.cpp VAD is the intended upgrade.
