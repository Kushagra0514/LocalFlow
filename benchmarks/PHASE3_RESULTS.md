# Phase 3 local S1-mini cleanup results

> Historical v0.1 record. Local S1/llama.cpp cleanup is not part of v0.2.

Date: 2026-08-28

## Outcome

LocalFlow now cleans successful Whisper transcripts entirely on the computer
with the pinned `llama.cpp` runtime and `S1-mini by Superwhisper` Q4_K_M model.
Groq, its API-key handling, and `python-dotenv` have been removed from the
application, project dependencies, lockfile, and virtual environment.

If local cleanup fails, LocalFlow reports the error and copies the successful
raw Whisper transcript. An empty S1-mini result is accepted as the correct
result for filler-only input rather than being mistaken for a failure.

## Implementation

- Runtime: `.local/phase1/llama/llama-server.exe` at pinned build `b10516`
- Model: `.local/phase1/models/s1-mini-q4_k_m.gguf`
- CPU thread limit: `min(4, available logical processors)`
- Context: 2,048 tokens
- Runtime lifecycle: one temporary process per cleanup request
- Listener: a randomly selected port on `127.0.0.1` only
- Request/response format: local OpenAI-compatible JSON endpoint
- Thinking: disabled with `{"enable_thinking":false}` through the Jinja chat
  template
- Sampling: temperature 0, top-k 1, and seed 0
- Output budget: estimated input tokens multiplied by 1.3, plus 32, capped at
  1,024 tokens

The temporary local server is stopped after every response. Whisper and
S1-mini therefore do not occupy memory at the same time. Using the structured
JSON response also ensures that llama.cpp console banners and timing logs can
never be copied as dictated text.

## Prompt contract

The application uses the model's required system prompt verbatim:

> You are a text normalizer for speech-to-text transcripts. The input begins
> with a control line specifying the styling, structure, and context settings;
> clean the transcript to match those settings and output only the cleaned
> text.

Every user message begins with:

```text
[Styling: semi-formal] [Structure: prose] [Context: general]
```

## Functional checks

Ten checks pass with Python's standard `unittest` runner. The five new Phase 3
checks cover the real local model, a missing runtime, the output budget, raw
transcript fallback, and a valid empty response.

The deterministic correction sample is:

> so um i need to like send the the report by uh friday no wait make that
> thursday

S1-mini returns:

> So I need to send the report by Thursday.

A real-model request containing only `um uh` returns an empty string, confirming
the filler-only case in addition to the automated control-flow test.

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Complete-pipeline measurement

The test system and pinned artifact checksums are recorded in
[`PHASE1_RESULTS.md`](PHASE1_RESULTS.md). Three runs used the 11-second fixed
audio sample, loaded each native process for each request, and used four CPU
threads.

| Measurement | Run 1 | Run 2 | Run 3 | Median |
| --- | ---: | ---: | ---: | ---: |
| Whisper | 3.94 s | 4.17 s | 3.73 s | 3.94 s |
| S1-mini | 4.62 s | 3.90 s | 4.07 s | 4.07 s |
| End to end | 8.56 s | 8.08 s | 7.80 s | 8.08 s |

The maximum observed combined working set of the Python controller and its
active native executable was **891.0 MiB**. This is below the 1 GiB target.
The monitor sampled every 50 ms and included the benchmark Python process plus
each newly started `whisper-cli` or `llama-server` process.

Absolute latency is sensitive to machine load and power state, as already seen
in Phase 2. These measurements demonstrate the current resource budget; older
and low-resource hardware still needs separate release validation.

## Local-only status

Inference uses only local executable and model paths. The only HTTP request in
the cleanup path targets the short-lived llama.cpp process bound to
`127.0.0.1`; there is no cloud endpoint or API credential. A formal
network-disabled release test remains in Phase 6.
