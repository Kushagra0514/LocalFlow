# Phase 5 recording-pipeline reliability results

> Historical v0.1 record. References to local S1/llama.cpp describe the retired
> architecture.

Date: 2026-08-28

## Outcome

LocalFlow now has one explicit, locked application state: `ready`, `recording`,
`processing`, or `shutting_down`. A recording reserves the pipeline before the
microphone opens, and processing keeps it reserved until transcription,
cleanup, and clipboard handling finish. Rapid hotkey use therefore cannot
start overlapping workers or produce out-of-order clipboard results.

## State behavior

The normal sequence is:

```text
ready -> recording -> processing -> ready
```

Shutdown can replace any state with `shutting_down`. That transition is final
for the running process.

- A hotkey press during `processing` prints `Still processing; recording
  ignored.`
- Repeated presses while already recording do nothing.
- A microphone-open failure returns to `ready` with an actionable error.
- Any transcription or clipboard failure returns to `ready`.
- Cleanup failure still preserves the raw Whisper transcript as implemented in
  Phase 3.

## Recording bounds

- Minimum accepted duration: 0.3 seconds, or 4,800 samples at 16 kHz.
- Maximum duration: 60 seconds.
- Maximum buffered audio: 960,000 mono float32 samples, approximately 3.7 MiB
  before Python and array-object overhead.

A timer ends a recording at 60 seconds. The callback independently refuses to
append samples beyond the exact sample cap, so a delayed timer cannot cause
unbounded memory growth. Recordings below the minimum are discarded before a
worker or native model process starts.

## Resource cleanup

Whisper now uses an explicitly managed process rather than `subprocess.run`.
Whisper and llama.cpp register their one active native process with the
application and clear it in `finally` cleanup.

During shutdown LocalFlow:

1. enters `shutting_down` under the state lock;
2. removes keyboard hooks and cancels the duration timer;
3. stops and closes the microphone stream;
4. terminates the active Whisper or llama.cpp process;
5. waits briefly for the worker and force-kills a native process if needed;
6. rejects any clipboard copy or automatic paste attempted by late background
   work.

Stream stop/close errors, model startup failures, model timeouts, clipboard
failures, and automatic-paste failures are reported without leaving the
application in a falsely busy state.

## Verification

All 25 tests pass. Seven new Phase 5 tests cover:

- the `ready -> recording -> processing` transition and single-worker rule;
- a `Still processing` response instead of a second recording;
- the exact maximum sample cap;
- rejection of a recording below 0.3 seconds;
- recovery from microphone-open failure;
- recovery from clipboard failure;
- prevention of copy/paste after shutdown; and
- termination of a registered native process during shutdown.

Existing real-model checks also confirm that both Whisper and S1-mini clear
their registered process after completing.

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
