# LocalFlow implementation plan

## Goal

Provide fully local, CPU-first push-to-talk English dictation on 64-bit
Windows, using whisper.cpp and S1-mini by Superwhisper while keeping the full
process tree below 1 GiB on the measured baseline.

## Phase 1: Prove the local inference stack

- [x] Pin Windows CPU builds of whisper.cpp and llama.cpp.
- [x] Verify the Whisper `base.en` Q5 and S1-mini Q4_K_M model files.
- [x] Transcribe fixed English audio and clean it with deterministic S1-mini.
- [x] Select official executables controlled by Python after measuring memory,
  latency, reliability, and packaging complexity.
- [x] Record measurements on a modern system.
- [ ] Repeat measurements on representative low-resource hardware.

Results: [`benchmarks/PHASE1_RESULTS.md`](benchmarks/PHASE1_RESULTS.md).

## Phase 2: Replace Faster-Whisper

- [x] Replace Faster-Whisper with whisper.cpp.
- [x] Preserve 16 kHz mono recording and bounded CPU thread use.
- [x] Return clear errors for missing runtime or model files.
- [x] Skip cleanup for no-speech results and test fixed-audio transcription.

Results: [`benchmarks/PHASE2_RESULTS.md`](benchmarks/PHASE2_RESULTS.md).

## Phase 3: Replace Groq with local S1-mini cleanup

- [x] Use llama.cpp and S1-mini by Superwhisper Q4_K_M locally.
- [x] Use the model's required system prompt and control line.
- [x] Disable thinking and use deterministic decoding.
- [x] Limit output and accept an empty cleanup result for filler-only speech.
- [x] Preserve the raw transcript if cleanup fails.

Results: [`benchmarks/PHASE3_RESULTS.md`](benchmarks/PHASE3_RESULTS.md).

## Phase 4: Improve hotkey and output behavior

- [x] Support single-key and modifier-combination hotkeys in `config.txt`.
- [x] Validate hotkeys at startup and ignore repeat events.
- [x] Stop safely when a trigger or required modifier is released.
- [x] Keep `f23` for Copilot-key users.
- [x] Always copy successful text and make automatic paste opt-in.

Results: [`benchmarks/PHASE4_RESULTS.md`](benchmarks/PHASE4_RESULTS.md).

## Phase 5: Make the recording pipeline reliable

- [x] Use explicit ready, recording, processing, and shutting-down states.
- [x] Permit one job at a time and bound recording duration.
- [x] Handle short recordings, microphone, model, subprocess, clipboard, and
  shutdown errors without leaving recording active.

Results: [`benchmarks/PHASE5_RESULTS.md`](benchmarks/PHASE5_RESULTS.md).

## Phase 6: Remove the old stack and secure local data

- [x] Remove Groq, API-key handling, Faster-Whisper, and python-dotenv.
- [x] Ignore models, runtimes, temporary audio, logs, build artifacts, and
  environment files.
- [x] Remove temporary recordings after processing.
- [x] Verify normal local operation rejects external network connections.
- [ ] Rotate an old Groq key if it was ever shared.

Results: [`benchmarks/PHASE6_RESULTS.md`](benchmarks/PHASE6_RESULTS.md).

## Phase 7: Model management, licensing, and packaging

- [x] Download pinned models during first-run setup and verify checksums.
- [x] Store models outside the source tree in a user data directory.
- [x] Include runtime, model, and package license notices.
- [x] Produce a repeatable Windows x64 package without developer tools.
- [ ] Test install and removal on a separate clean Windows account.

Results: [`benchmarks/PHASE7_RESULTS.md`](benchmarks/PHASE7_RESULTS.md).

## Phase 8: Documentation and release verification

- [x] Document setup, usage, configuration, privacy, supported hardware, and
  troubleshooting.
- [x] Document hotkey combinations, opt-in automatic paste, and English-only
  cleanup.
- [x] Test configuration/state behavior, missing models, microphone failure,
  invalid hotkeys, empty speech, cleanup fallback, and shutdown.
- [x] Add a fixed-audio packaged transcription-and-cleanup smoke test.
- [x] Measure complete-process-tree working set and first/repeat latency.

Results: [`benchmarks/PHASE8_RESULTS.md`](benchmarks/PHASE8_RESULTS.md).

## Deferred until measurements justify them

- A graphical settings interface.
- Multiple transcription backends.
- GPU-, NPU-, Vulkan-, CUDA-, or OpenVINO-specific packages.
- Automatic hardware detection and model selection.
- Multilingual cleanup.
- Streaming partial transcripts.
