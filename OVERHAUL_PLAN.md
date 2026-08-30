# LocalFlow v0.2 architecture overhaul plan

## How to use this plan

Every task has a stable identifier. You can ask for one step, such as
`Implement Step 3.2`, or a complete phase, such as `Implement Phase 5`.
After implementation and verification, mark only the completed boxes and add
the relevant test or measurement result to this file.

This plan supersedes the architecture in `IMPLEMENTATION_PLAN.md`; that file
remains the historical record for the v0.1 local-cleanup implementation.

## Goal

Build a maintainable Windows application with:

- local, English-only transcription using whisper.cpp `base.en` Q5;
- no local cleanup model and no llama.cpp runtime;
- optional cloud transcript cleanup when cleanup is explicitly enabled;
- a separate push-to-talk command hotkey for cloud-interpreted commands;
- Groq as the first BYOK cloud provider;
- a provider boundary that can later support OpenAI, Gemini, or Claude without
  changing recording, transcription, output, or tool implementations; and
- explicit feature and tool registries so additions do not create more
  conditionals in the stable application core.

“Dynamic” in this plan means modular composition through small registries and
stable data contracts. It does not mean automatic loading of arbitrary Python
files, runtime code generation, or a heavyweight plugin framework.

## Decisions that are already settled

- Windows 10/11 x64 remains the supported platform for v0.2.
- Transcription remains local and English-only.
- The pinned transcription model remains `ggml-base.en-q5_1.bin`.
- Cleanup defaults to off.
- Command mode defaults to off.
- Normal dictation never contacts a cloud provider when cleanup is off.
- Only transcript text is sent to a provider; recorded audio is never sent.
- API keys are BYOK and are never stored in `config.ini`.
- Missing credentials or cloud failures never stop local transcription.
- Cleanup failure preserves and publishes the raw Whisper transcript.
- Command mode uses a separate hotkey and does not run transcript cleanup.
- Successful commands are neither copied nor automatically pasted.
- Failed commands launch nothing, copy the raw command for recovery, and never
  automatically paste it.
- Provider output is untrusted and cannot become a shell command, executable
  path, or argument list.
- There will be no separate “Groq extension” installer payload. The small
  cloud integration ships dormant and consumes no API usage unless enabled.

## Current baseline and known inconsistencies

The pre-overhaul test baseline is:

- 36 tests discovered;
- 33 passing; and
- 3 skipped because local native/model fixtures are unavailable.

The following inconsistencies must be resolved before a release:

- `main.py` uses `base.en`, while parts of the README, notices, and package
  test still refer to `small.en`.
- `config.txt` sets cleanup to false, while the in-code and documented defaults
  still say true in places.
- the build continues to download and package llama.cpp even when cleanup is
  disabled;
- the package test still expects the S1 model; and
- version information is duplicated across several files.

The worktree already contains user changes. Every implementation phase must
preserve them unless that phase deliberately replaces the same behavior.

## Target source layout

The exact line counts may change, but responsibilities should end in this
shape:

```text
main.py                         Thin CLI/bootstrap only
config.default.ini              Shipped defaults, never a live user config
localflow/
  __init__.py                   Package metadata
  types.py                      Shared immutable jobs and results
  application.py                Lifecycle, state, worker, shutdown
  config.py                     INI loading, migration, typed validation
  recording.py                  Hotkeys, microphone, bounded audio capture
  whisper.py                    Model management and local transcription
  pipeline.py                   Mode-to-handler routing and fallback policy
  cloud.py                      Provider-neutral requests and HTTP adapter
  commands.py                   Tool-call validation and explicit registry
  output.py                     Clipboard and opt-in automatic paste
  tools/
    __init__.py                 Built-in tool registration
    open_app.py                 Windows app discovery and safe launch
tests/
  test_config.py
  test_recording.py
  test_whisper.py
  test_pipeline.py
  test_output.py
  test_cloud.py
  test_commands.py
  test_application.py
```

This is a target boundary, not permission to create empty scaffolding. Create a
module only when its implementation is moved into it.

## Architecture rules

1. `main.py` assembles components and handles CLI arguments; it contains no
   recording, inference, provider, or tool behavior.
2. Recording produces a job with a fixed purpose: `DICTATION` or `COMMAND`.
   That purpose cannot change after recording starts.
3. Whisper accepts audio and returns text. It knows nothing about cleanup,
   cloud providers, commands, clipboard behavior, or application launching.
4. The pipeline routes completed transcripts to a registered handler by job
   purpose. It contains no provider-specific JSON.
5. The cloud module converts one internal request format to one provider API
   and normalizes its response. Prompts remain with the feature using them.
6. The command dispatcher accepts only a validated tool name and validated
   arguments from an explicit allowlist.
7. A tool implementation never receives raw provider JSON.
8. Future tools require a new tool module, its tests, and one explicit
   registration. They do not modify recording, Whisper, or the state machine.
9. Future OpenAI-compatible providers require provider data and contract tests.
   A provider with a genuinely different API gets a small adapter behind the
   same internal boundary.
10. No feature may bypass the shutdown check immediately before clipboard,
    paste, or tool side effects.

## Proposed user configuration

The live file will be `%LOCALAPPDATA%\LocalFlow\config.ini`. The application
will print this location at startup and expose a `--config-path` command.

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

English and `base.en` remain pinned in code for this release. Do not add
unsupported language, model URL, checksum, arbitrary API endpoint, or shell
configuration knobs.

Secrets remain outside this file. Initially, Groq reads `GROQ_API_KEY` from
the current user’s environment. Later providers may use their corresponding
provider-specific environment variables.

---

## Phase 0: Preserve the baseline and reconcile current work

### Steps

- [x] **0.1** Review every currently modified file and separate intentional
  user changes from obsolete `small.en` and local-cleanup work. Do not reset or
  discard the dirty worktree.
- [x] **0.2** Create an overhaul branch and make a recoverable checkpoint before
  deleting or moving implementation files.
- [x] **0.3** Make all current source, test, package, README, and notice references
  agree on English `base.en` Q5 and cleanup disabled by default.
- [x] **0.4** Run the existing unit suite and record its exact result here.
  Baseline on 2026-08-30: 36 tests discovered, 33 passed, and 3 native-fixture
  integration tests skipped; runtime 0.687 seconds.
- [x] **0.5** Record the current ZIP/installer size and the most recent local
  transcription memory and latency measurements for before/after comparison.
- [x] **0.6** Add a release-consistency check for the selected Whisper filename,
  cleanup default, and application version so these values cannot silently
  drift across source, packaging, and tests again.

### Exit criteria

- Current work is recoverable.
- All active files agree on `base.en` and current defaults.
- The local transcription baseline passes before architectural changes begin.
- Release metadata drift is caught automatically.

### Results

- Reviewed the seven checkpointed files. The cleanup toggle and its tests were
  retained; stale `small.en` edits were reconciled to `base.en`; no user change
  was reset or discarded.
- Created branch `codex/v0.2-overhaul` and checkpoint commit `cfe04f9` before
  reconciliation.
- Pre-reconciliation baseline on 2026-08-30: 36 tests discovered, 33 passed,
  and 3 native-fixture integration tests skipped.
- Post-reconciliation suite: 39 tests discovered, 36 passed, and 3
  native-fixture integration tests skipped; final runtime 2.265 seconds. The three
  added tests enforce model, default, and version consistency.
- Existing extracted package: 105,435,880 bytes. Existing ZIP: 43,670,218
  bytes, SHA-256
  `5c9629c059b4080ecc1716249c3fab4216b4fa6c81c9ee34682a632979c401dd`.
  Existing installer: 27,943,378 bytes, SHA-256
  `1b2c74395127c9ef2767465948f42105fd1370d3cfc6690882c0488d990624b2`.
- Fresh cleanup-disabled packaged smoke test on 2026-08-30: Whisper 5.120
  seconds, complete pipeline 5.121 seconds, and 265.2 MiB peak process-tree
  working set. The fixed sample produced the expected JFK transcript.
- Historical published v0.1.1 cleanup-enabled measurements remain in
  `benchmarks/PHASE8_RESULTS.md`: 3.05–3.35 second repeat pipeline latency and
  939.9 MiB maximum observed process-tree working set. They are retained only
  as a before-overhaul comparison.

---

## Phase 1: Remove the local S1/llama.cpp cleanup stack

### Steps

- [x] **1.1** Remove S1 constants, prompts, model specifications, token limits,
  health checks, local HTTP calls, and cleanup functions from the application.
- [x] **1.2** Remove llama.cpp validation, process startup, shutdown, and smoke
  test branches while preserving whisper.cpp process cancellation.
- [x] **1.3** Make the interim dictation pipeline always publish raw Whisper
  text; do not introduce cloud behavior in this phase.
- [x] **1.4** Remove S1/llama-specific tests and retain tests proving raw
  transcription fallback, recording bounds, one-job-at-a-time behavior,
  clipboard handling, and shutdown safety.
- [x] **1.5** Remove the llama.cpp archive download, extraction, DLL list,
  runtime folder, and manifest entries from `packaging/build_windows.ps1`.
- [x] **1.6** Change the package test to seed and verify only the pinned
  `ggml-base.en-q5_1.bin` model.
- [x] **1.7** Remove S1-mini and llama.cpp from current third-party notices and
  stop packaging their license files.
- [x] **1.8** Add precise installer-upgrade deletion entries for obsolete files
  under the installed `runtime\llama` and obsolete packaged licenses. Never
  delete the entire installation or user-data directory.
- [x] **1.9** Leave an existing
  `%LOCALAPPDATA%\LocalFlow\models\s1-mini-q4_k_m.gguf` untouched and document
  its exact optional manual-removal path.
- [x] **1.10** Rebuild and verify that no llama executable, S1 model, `.gguf`, or
  obsolete license remains inside the ZIP or installer.

### Exit criteria

- LocalFlow downloads and requires only the Whisper model.
- The packaged application contains only the whisper.cpp native inference
  runtime.
- Local dictation works offline after the Whisper model is present.
- Old user model data is not silently deleted.

### Phase 1 verification result (2026-08-30)

- Unit suite: 34 tests discovered, 32 passed, and 2 real-audio source-tree
  fixture tests skipped. The packaged fixed-audio smoke test passed separately.
- ZIP smoke test: the fixed sample produced the expected raw transcript with no
  network-dependent cleanup step; peak process-tree working set was 263.6 MiB.
- Four rebuilt-package measurements: Whisper/raw pipeline 2.61–3.72 seconds;
  peak process-tree working set 264.0–265.2 MiB.
- Package and installer tests rejected `.gguf`, llama, and S1 files. The
  installer upgrade test also removed a simulated obsolete `runtime\llama`
  directory and obsolete licenses while preserving the user's `config.txt`.
- Rebuilt ZIP: 26,267,007 bytes (25.05 MiB), SHA-256
  `d13d40b3043e2dc6201e574aa8910bdcedfaf498cb415f2ec2401e0d0d867911`.
- Rebuilt installer: 18,824,204 bytes (17.95 MiB), SHA-256
  `a1cad7b808d3dab6b2025f7002a7e141411c7ae9f161ab22d41fad3818a172c8`.

---

## Phase 2: Extract the stable local core from `main.py`

### Steps

- [x] **2.1** Add only the small enums and immutable data objects required to
  represent application state, job purpose, recordings, and results.
- [x] **2.2** Move model download, checksum verification, WAV conversion,
  whisper.cpp validation, transcription, and cancellation into
  `localflow/whisper.py` without changing behavior.
- [x] **2.3** Move hotkey parsing, key-repeat handling, microphone ownership,
  duration limits, and audio buffering into `localflow/recording.py`.
- [x] **2.4** Replace recording-related module globals with one recorder object
  whose stream, timer, buffer, and active job purpose are owned together.
- [x] **2.5** Move clipboard copy and opt-in paste behavior into
  `localflow/output.py`, including the final shutdown guard.
- [x] **2.6** Create `localflow/pipeline.py` with an explicit mapping from job
  purpose to transcript handler. Initially register only raw dictation.
- [x] **2.7** Create `localflow/application.py` to own the explicit state machine,
  lock, single worker, active native process, startup, and shutdown.
- [x] **2.8** Reduce `main.py` to argument parsing, component construction, startup,
  and exit-code handling.
- [x] **2.9** Split the monolithic test file by responsibility while moving each
  implementation. Avoid permanent compatibility shims back through `main.py`.
- [x] **2.10** Run the complete unit suite after every module extraction, then run
  the real fixed-audio Whisper smoke test.

### Exit criteria

- `main.py` contains no business logic.
- Tests can replace the transcriber, output publisher, and handlers without
  patching globals in `main`.
- Recording and Whisper have no imports from cloud or command modules.
- Existing local behavior and shutdown guarantees remain intact.

### Phase 2 verification result (2026-08-30)

- `main.py` fell from 827 lines to 93 lines and now contains only path/config
  wiring, component construction, CLI dispatch, and exit-code handling.
- Responsibility-specific suites passed after extraction. The final complete
  suite discovered 44 tests: 43 passed and 1 source-tree real-audio fixture
  test skipped because that optional fixture is unavailable.
- Tests replace the transcriber, output publisher, and pipeline handlers by
  constructor injection; no compatibility business-logic shims remain in
  `main.py`.
- The final packaged fixed-audio smoke test produced the expected transcript in
  1.228 seconds with a 264.0 MiB peak process-tree working set.
- The final installer passed silent install, config-preserving upgrade,
  obsolete-file cleanup, launch, uninstall, and test-directory cleanup.
- Rebuilt ZIP: 26,276,208 bytes (25.06 MiB), SHA-256
  `1b71dcc7211592e8ac12488313ce24483f4bbb29a1d889c65e116f7206b3f60f`.
- Rebuilt installer: 18,840,172 bytes (17.97 MiB), SHA-256
  `a3f0194796d7b44d21c690a39ddca14552d8634add5a5463e058b9a4bcb28c85`.

---

## Phase 3: Replace `config.txt` with one canonical `config.ini`

### Steps

- [x] **3.1** Add `config.default.ini` containing the documented safe defaults.
- [x] **3.2** Parse configuration with Python’s standard-library
  `configparser` in `localflow/config.py`.
- [x] **3.3** Return one immutable, typed configuration object and validate all
  values once at startup. Other modules receive values; they never read files.
- [x] **3.4** Store the live configuration at
  `%LOCALAPPDATA%\LocalFlow\config.ini`, using `LOCALFLOW_DATA_DIR` to isolate
  tests.
- [x] **3.5** On first run only, if no INI exists, import the legacy `HOTKEY` and
  `AUTO_PASTE` values from `config.txt` beside the executable.
- [x] **3.6** Do **not** migrate legacy `CLEANUP=true`. It previously meant local
  processing; carrying it forward would silently opt the user into transmitting
  transcripts to a cloud service. Always initialize new cloud cleanup to false.
- [x] **3.7** Write the migrated/default INI atomically and leave the old TXT file
  untouched for rollback. Never merge or overwrite an existing INI.
- [x] **3.8** Add `--config-path` and `--check-config` commands and print the live
  path during ordinary startup.
- [x] **3.9** Reject unknown sections or keys, unknown providers, invalid
  booleans/timeouts, malformed hotkeys, and conflicting dictation and command
  bindings with actionable messages.
- [x] **3.10** Ensure installer upgrades never replace the user-data INI and stop
  shipping a live configuration beside `LocalFlow.exe`.
- [x] **3.11** Test defaults, valid edits, invalid values, first-run creation,
  legacy import, privacy-safe cleanup migration, existing-INI preservation, and
  installer upgrade behavior.

### Exit criteria

- There is exactly one live configuration file.
- Users can reliably locate and validate it.
- Upgrading cannot silently enable cloud transmission.
- API keys and arbitrary API endpoints cannot be placed in the INI.

### Phase 3 verification result (2026-08-30)

- The complete unit suite discovered 58 tests: 57 passed and 1 source-tree
  real-audio fixture test skipped because that optional fixture is unavailable.
- Configuration tests covered safe defaults, typed immutable values, valid
  edits, malformed and unknown settings, provider/timeout/boolean/hotkey
  validation, atomic first-run creation, legacy migration, and byte-for-byte
  preservation of an existing INI.
- The packaged fixed-audio smoke test produced the expected transcript in 2.242
  seconds with a 263.7 MiB peak process-tree working set.
- The ZIP contains `config.default.ini` but no `config.txt` or live `config.ini`.
  The installed executable created and validated the sole live INI under an
  isolated user-data directory.
- The installer test migrated legacy `HOTKEY=f12` and `AUTO_PASTE=true`, forced
  cloud cleanup to false despite legacy `CLEANUP=true`, and preserved both the
  generated user-data INI and legacy TXT byte for byte during upgrade.
- Rebuilt ZIP: 26,305,634 bytes (25.09 MiB), SHA-256
  `e0c826d8a23697a1e61d9f3d9a23d587cf9ca9625532a08559c2f4db1d5efcb4`.
- Rebuilt installer: 18,868,857 bytes (17.99 MiB), SHA-256
  `573a4a9d876c269aef05e03a038a6826586b97aaffb940bac93d3b92d3cb4a21`.

---

## Phase 4: Add a provider-neutral cloud boundary and Groq adapter

### Steps

- [x] **4.1** Define the smallest internal request and response data needed for
  text completion and a single optional tool call.
- [x] **4.2** Keep prompts out of the transport layer; cleanup and command
  handlers construct their own messages.
- [x] **4.3** Implement one OpenAI-compatible HTTPS request path using the
  existing `urllib`, `json`, `certifi`, and Windows certificate context.
- [x] **4.4** Add an explicit provider registry containing Groq’s trusted base
  URL, API-key environment-variable name, supported model default, and any
  required headers. Do not accept a user-supplied base URL.
- [x] **4.5** Normalize successful text and tool-call responses before returning
  them to a feature. No feature may parse provider-specific JSON.
- [x] **4.6** Normalize timeout, TLS/DNS, authentication, permission, rate-limit,
  malformed-response, oversized-response, and server failures into safe
  application errors.
- [x] **4.7** Use a short bounded timeout, bounded request/response sizes, no
  streaming, and no automatic retries in the first implementation.
- [x] **4.8** Never put keys, authorization headers, transcripts, or raw provider
  response bodies into exceptions or logs.
- [x] **4.9** Add reusable provider contract tests using mocks and a local fake
  HTTP server. Standard tests must never require a real key, network, or billable
  request.
- [x] **4.10** Document how a future OpenAI-compatible provider is added through
  provider data and the same contract tests. Add a separate adapter only when a
  provider’s native API cannot satisfy the common contract.

### Exit criteria

- No Groq-specific JSON or authentication logic exists outside the cloud
  module.
- A fake provider can drive cleanup and command tests.
- Disabled features do not read credentials or construct a network request.
- Adding another compatible provider does not touch recording, Whisper,
  output, tools, or application state.

### Phase 4 verification result (2026-08-30)

- The complete unit suite discovered 73 tests: 72 passed and 1 source-tree
  real-audio fixture test skipped because that optional fixture is unavailable.
- Provider contract tests normalized plain text and exactly one parsed tool
  call through a loopback fake server. Mocked tests covered credentials,
  authentication, permission, rate limiting, request size, timeout, TLS, DNS,
  connection, server, oversized response, and malformed response failures.
- Tests assert one network attempt with no retries, bounded 64 KiB requests and
  256 KiB responses, non-streaming requests, and disabled parallel tool calls.
- Error tests include private marker values in keys, transcripts, HTTP details,
  and response bodies and confirm none appear in normalized exceptions.
- With cleanup and commands disabled, application construction neither creates
  a cloud client nor opens a network connection. No real credential, external
  provider request, or billable API call was used during verification.
- Groq's former `llama-3.1-8b-instant` default was retired for free/developer
  users on 2026-08-16, so new configurations use Groq's documented replacement,
  `openai/gpt-oss-20b`. Existing user INIs are intentionally not overwritten.
- The packaged fixed-audio smoke test produced the expected local transcript in
  2.169 seconds with a 264.0 MiB peak process-tree working set. Silent install,
  configuration-preserving upgrade, launch, and uninstall also passed.
- Rebuilt ZIP: 26,316,169 bytes (25.10 MiB), SHA-256
  `69822d109c7682da90a9362884a6ec879b4ac33b5182b7e1cc96da1f6d76e102`.
- Rebuilt installer: 18,873,282 bytes (18.00 MiB), SHA-256
  `d3a7d31baba88e68c514eb16d0d080a7ac7179423209383725fd13bd71033137`.

---

## Phase 5: Implement optional cloud transcript cleanup

### Steps

- [ ] **5.1** Add a dictation cleanup stage that is selected from typed config,
  not a global flag.
- [ ] **5.2** With cleanup disabled, publish the raw Whisper transcript directly
  without reading an API key or constructing a provider.
- [ ] **5.3** With cleanup enabled and credentials available, send only the raw
  transcript text with a tightly scoped cleanup prompt.
- [ ] **5.4** Require the cleanup response to contain only corrected transcript
  text while preserving meaning, names, numbers, and English wording.
- [ ] **5.5** Treat an empty, malformed, oversized, or failed response as cleanup
  failure and preserve the raw transcript.
- [ ] **5.6** Check shutdown before the request, after the response, before
  clipboard copy, and before automatic paste.
- [ ] **5.7** If credentials are missing, report cleanup as unavailable and use
  raw text without preventing startup or future dictation.
- [ ] **5.8** Avoid printing transcript contents or provider bodies in error
  messages. Clearly document any transcript text still shown in the console.
- [ ] **5.9** Test the complete matrix of cleanup disabled/enabled, key
  missing/present, success/failure, empty response, clipboard error, automatic
  paste, and shutdown during the request.
- [ ] **5.10** Add an offline assertion proving cleanup-disabled dictation makes
  no external connection.

### Exit criteria

- `cleanup.enabled = false` preserves fully local dictation.
- `cleanup.enabled = true` sends transcript text, never audio.
- Every cleanup failure returns the successful raw transcript.
- Cloud cleanup adds no native model or runtime memory requirement.

---

## Phase 6: Add the separate command recording mode

### Steps

- [ ] **6.1** Generalize hotkey bindings so each binding carries a fixed job
  purpose instead of calling dictation-specific callbacks.
- [ ] **6.2** Register the dictation hotkey for `DICTATION` and the command
  hotkey for `COMMAND` using the same parser and recorder.
- [ ] **6.3** Require different trigger keys in the first release so one shortcut
  cannot be a modifier-extended version of the other.
- [ ] **6.4** Capture the job purpose when recording starts and pass it unchanged
  with the audio to the single processing worker.
- [ ] **6.5** Ignore the other hotkey while recording or processing, and ensure
  releasing it cannot stop or reroute the active recording.
- [ ] **6.6** Register command mode only when it is enabled and valid provider
  credentials are available. Local dictation must remain available otherwise.
- [ ] **6.7** Transcribe command audio locally with the same English Whisper path,
  skip cleanup, and make exactly one provider interpretation request.
- [ ] **6.8** Initially connect command mode to a fake/no-action handler before
  allowing real application side effects.
- [ ] **6.9** Test single keys, combinations, repeats, early modifier release,
  collisions, simultaneous bindings, mode preservation, one-job-at-a-time
  behavior, and shutdown after a delayed provider response.

### Exit criteria

- The hotkey pressed at recording start unambiguously determines the pipeline.
- Normal dictation and command recordings cannot overlap or reroute each other.
- Command mode can be tested without opening a real application.
- No command transcript is cleaned, copied, or pasted on a successful command.

---

## Phase 7: Add the safe tool registry and `open_app`

### Steps

- [ ] **7.1** Define a small tool description containing a stable name,
  description, JSON-compatible argument schema, validator, and handler.
- [ ] **7.2** Build an explicit allowlisted registry. Do not scan the filesystem,
  import arbitrary modules, or execute model-provided code.
- [ ] **7.3** Expose only `open_app` to Groq in the first release. A missing tool
  call means no action rather than a second executable tool.
- [ ] **7.4** Accept exactly one tool call named `open_app` with exactly one
  non-empty string field named `app_name`.
- [ ] **7.5** Apply a short length limit and reject control characters, paths,
  URLs, extra properties, multiple calls, unknown tools, and malformed JSON.
- [ ] **7.6** Build a local application catalogue from current-user/all-users
  Start Menu `.lnk` files and trusted Windows App Paths registry entries.
- [ ] **7.7** Keep only existing trusted shortcut or absolute executable targets,
  normalize display names, executable stems, and duplicates locally, and never
  send the catalogue to the provider.
- [ ] **7.8** Prefer exact normalized matches. Permit a partial match only when it
  is unique and clearly report missing or ambiguous names instead of guessing.
- [ ] **7.9** Launch only the resolved catalogue entry through `os.startfile()`.
  Never use PowerShell, `cmd.exe`, `shell=True`, model-provided paths, executable
  arguments, `eval`, or `exec`.
- [ ] **7.10** Check application shutdown immediately before dispatch and again
  inside the launcher boundary.
- [ ] **7.11** On success, print a local status message and do not copy or paste
  the spoken command. On any failure, launch nothing, copy the raw command, and
  never auto-paste it.
- [ ] **7.12** Add adversarial tests for traversal, absolute paths, URLs, NUL and
  control characters, shell separators, unknown functions, extra arguments,
  multiple calls, prompt-injection text, missing apps, and ambiguous apps.
  Every rejection must assert that the launcher was not called.
- [ ] **7.13** Manually verify Chrome, Notepad, one current-user application, an
  absent application, and an ambiguous name on Windows.

### Exit criteria

- Groq may select an allowlisted action but can never execute it directly.
- Untrusted output cannot become a path, argument list, or shell command.
- Users do not need to configure paths for ordinary Start Menu/App Paths apps.
- Adding another tool requires a new module, tests, and one explicit registry
  entry—not changes to recording, Whisper, state, or cloud transport.

---

## Phase 8: Finish packaging, migration, documentation, and release verification

### Steps

- [ ] **8.1** Update package metadata and descriptions from “fully local” to
  “local-first with optional cloud features,” while clearly preserving the
  fully local cleanup-off mode.
- [ ] **8.2** Use one authoritative application version or add a test that fails
  when `main`, `pyproject.toml`, the build manifest, and Inno Setup disagree.
- [ ] **8.3** Set the overhaul release version to the selected `0.x.x` minor
  release after all behavior is complete.
- [ ] **8.4** Update README installation, configuration location, API-key setup,
  cleanup behavior, command hotkey, privacy boundary, fallback behavior,
  troubleshooting, uninstall, and stale S1-model cleanup instructions.
- [ ] **8.5** Update third-party notices and generated dependency licenses to
  exactly match the new package contents.
- [ ] **8.6** Keep historical v0.1 benchmark files as historical evidence, but
  ensure no current documentation presents S1/llama measurements as v0.2
  performance.
- [ ] **8.7** Update the packaged smoke test to cover fixed-audio local
  transcription with cleanup and commands disabled.
- [ ] **8.8** Add a deterministic fake-provider end-to-end test covering fixed
  audio, cleanup success/fallback, command interpretation, validation, and a
  mocked launcher.
- [ ] **8.9** Keep any real Groq smoke test opt-in, manual, and outside normal CI
  and packaging tests to avoid secrets, cost, and network flakiness.
- [ ] **8.10** Assert ZIP and installed contents contain no llama.cpp, S1 model,
  `.gguf`, obsolete notices, test credentials, or partial downloads.
- [ ] **8.11** Test fresh install, legacy-config upgrade, second upgrade with an
  existing INI, launch, configuration discovery, uninstall, and exact stale
  runtime removal on an isolated Windows account.
- [ ] **8.12** Verify networking disabled: local dictation works; cleanup safely
  falls back; command mode launches nothing; the application returns to ready.
- [ ] **8.13** Remeasure installer/ZIP size, complete-process-tree peak memory,
  cold/warm local transcription latency, and cloud round-trip latency. Publish
  local and network-dependent measurements separately.
- [ ] **8.14** Run the complete unit, package, installer, fixed-audio, security,
  and manual test matrix from a clean checkout before tagging the release.

### Release criteria

- Local English dictation works with no cloud account, key, or network.
- Only the single pinned `base.en` model is downloaded.
- No local LLM, S1 model, or llama.cpp runtime ships.
- Cleanup and commands remain independently opt-in.
- Only opted-in transcript text is sent to the configured provider.
- All provider failures preserve local dictation and avoid unintended side
  effects.
- Provider output cannot become arbitrary local execution.
- The user has one discoverable, upgrade-safe `config.ini`.
- Future providers, modes, and tools can be added through their documented
  boundary without editing recording or Whisper.
- The installer, portable package, documentation, tests, notices, version, and
  measurements all describe the same release.

## Deferred until a later release justifies them

- Multilingual Whisper models or automatic language selection.
- A graphical settings and credential-management interface.
- Windows Credential Manager integration.
- Native Gemini or Claude adapters when the common endpoint is insufficient.
- Runtime third-party plugin discovery.
- Arbitrary shell commands or executable arguments.
- Multiple tool calls in one command.
- Destructive tools or tools that require confirmation workflows.
- Fuzzy application matching that can launch ambiguous results.
- Conversation history, background agents, or autonomous command loops.
- Streaming partial transcription.
- macOS or Linux packaging.

## Execution discipline

- Complete phases in order unless a step explicitly has no unmet dependency.
- Keep the application runnable at each phase exit.
- Do not combine config migration, module extraction, cloud behavior, and tool
  execution into one unreviewable change.
- Run the smallest relevant test after every non-trivial step and the complete
  suite at every phase exit.
- Never mark a checkbox complete merely because code was written; its tests and
  exit criteria must pass.
- Preserve unrelated user changes in the dirty worktree.
- Update this document with actual results and any consciously deferred risk.
