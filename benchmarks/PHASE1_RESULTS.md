# Phase 1 local inference results

Date: 2026-08-28

## Outcome

The local inference stack works. The selected integration for the current
Python application is to run the official whisper.cpp and llama.cpp command-line
executables sequentially. This keeps the estimated complete application peak
below 1 GiB without adding third-party Python bindings.

Keeping both model servers resident reduces latency, but it is not selected for
the current Python application because the estimated complete peak exceeds the
1 GiB target.

## Test system

- CPU: Intel Core Ultra 7 155H
- Logical processors: 22
- Test thread limit: 4
- Available physical memory reported to .NET: 31.4 GiB
- OS: Windows 10.0.26200, x64
- Dedicated GPU acceleration: not used

This is a modern development computer, not the representative low-resource
computer required for release validation.

## Pinned artifacts

| Artifact | Pin | Verification |
| --- | --- | --- |
| whisper.cpp Windows x64 CPU build | `b4938` | ZIP SHA-256 `c2a4b60edb11f7e11a9191ffb50929535527d4d91c9903dbe3e554583bbbc63d` matches the GitHub release digest |
| Whisper model | `ggml-base.en-q5_1.bin` | SHA-1 `d26d7ce5a1b6e57bea5d0431b9c20ae49423c94a` matches the official model repository |
| llama.cpp Windows x64 CPU build | `b10516` | ZIP SHA-256 `fbbbc55e0eb2e1b07f9dcb9488616c98ed47d9003b90e15e7c8c7812c4307cd3` matches the GitHub attestation |
| S1-mini by Superwhisper | `s1-mini-q4_k_m.gguf` | Downloaded SHA-256 `3b41ebe2502cbd03e811d5d16b022f5ab551eda58d62597d152f89535003c634` |
| Fixed audio sample | whisper.cpp `jfk.wav` at `b4938` | SHA-256 `59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e` |

S1-mini's direct `v1` file URL returned HTTP 404. The evaluation therefore
uses the official `main` file and pins the exact downloaded bytes by SHA-256.

## Functional result

Whisper transcription:

> And so my fellow Americans, ask not what your country can do for you, ask
> what you can do for your country.

S1-mini returned the same clean sentence, which is correct because the source
was already punctuated. A second deterministic cleanup check used:

> so um i need to like send the the report by uh friday no wait make that
> thursday

S1-mini returned:

> So I need to send the report by Thursday.

Both checks used the documented system prompt and control line, thinking
disabled, temperature 0, a 1,024-token context, and four CPU threads.

## One-shot executable measurements

Each measurement starts a new process and therefore includes model startup.
The filesystem cache was already warm. Peak memory is the native process
working set; the estimated complete peak below also includes the measured
current Python audio/hotkey controller process tree.

| Run | Elapsed | Peak working set |
| --- | ---: | ---: |
| Whisper 1 | 1,196.6 ms | 214.3 MiB |
| Whisper 2 | 1,190.2 ms | 215.2 MiB |
| Whisper 3 | 1,171.3 ms | 213.3 MiB |
| S1-mini 1 | 2,657.0 ms | 774.9 MiB |
| S1-mini 2 | 2,077.4 ms | 775.1 MiB |
| S1-mini 3 | 2,164.8 ms | 775.5 MiB |

- Median sequential processing time: about 3.36 seconds for the 11-second
  sample.
- Maximum observed native-model working set: 775.5 MiB.
- Measured current Python controller process tree: approximately 164.6 MiB.
- Estimated sequential complete-application peak: approximately 940.1 MiB.

The first direct Whisper run after download reported 1,368.4 ms internally.
A true cold-disk benchmark requires a reboot or cache-control procedure and is
deferred to release hardware validation.

## Persistent-server measurements

Both official servers were loaded together with 1,024 tokens of S1-mini
context and four CPU threads.

| Measurement | Result |
| --- | ---: |
| Whisper server idle | 122.0 MiB |
| S1-mini server idle | 761.9 MiB |
| Combined server idle | 883.8 MiB |
| Combined after Whisper request | 930.0 MiB |
| Combined after S1-mini request | 942.9 MiB |
| Warm Whisper request | 847.4 ms |
| Warm S1-mini request | 698.2 ms |

The current Python controller adds approximately 164.6 MiB across its launcher
and interpreter. The estimated persistent complete-application peak is
therefore approximately 1,107.5 MiB, above the target.

## Integration decision

Use official executables controlled by Python, with sequential model process
lifetimes, for the next implementation phase.

Reasons:

- It passed the functional checks using upstream-supported executables.
- It avoids compiler and Python-binding installation problems.
- Its estimated complete peak remains below 1 GiB.
- The model subprocess boundary gives a straightforward raw-transcript
  fallback if cleanup fails.

Tradeoff: loading S1-mini for each dictation adds roughly 1.5 seconds on this
machine compared with keeping both servers resident. This tradeoff must be
remeasured on low-resource hardware. If latency is unacceptable, a native
application using the whisper.cpp and llama.cpp libraries directly is the next
option; keeping both servers resident in the current Python stack is not.

## Offline status

All inference commands used local executable, model, and audio paths. Neither
runtime needed a network request after the artifacts were downloaded. A formal
offline application test remains part of the later release phase.

## Remaining Phase 1 validation

- Repeat the same benchmark on a representative older or low-resource Windows
  computer when one is available.
- Measure true cold-disk startup on that release-validation computer.

## Sources

- [whisper.cpp releases](https://github.com/ggml-org/whisper.cpp/releases)
- [Official Whisper GGML models](https://huggingface.co/ggerganov/whisper.cpp)
- [llama.cpp b10516 attestation](https://github.com/ggml-org/llama.cpp/attestations/41873046)
- [S1-mini GGUF](https://huggingface.co/superwhisper/s1-mini-GGUF)
