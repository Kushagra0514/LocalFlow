import hashlib
import os
import tempfile
import socket
import unittest
import wave
from io import BytesIO
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np

os.environ.setdefault(
    "LOCALFLOW_DATA_DIR", str(Path(__file__).parents[1] / ".local" / "phase1")
)

import main


SAMPLE_PATH = Path(__file__).parents[1] / ".local" / "phase1" / "samples" / "jfk.wav"
S1_SAMPLE = "so um i need to like send the the report by uh friday no wait make that thursday"


def load_sample_audio():
    with wave.open(str(SAMPLE_PATH), "rb") as wav_file:
        if (wav_file.getframerate(), wav_file.getnchannels()) != (16_000, 1):
            raise AssertionError("Phase 1 sample must be 16 kHz mono audio")
        audio = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype="<i2")
    return audio.astype(np.float32) / 32_768


class ModelManagementTest(unittest.TestCase):
    def model_spec(self, payload=b"model data"):
        return main.ModelSpec(
            "Test model",
            "test-model.bin",
            "https://example.invalid/test-model.bin",
            len(payload),
            hashlib.sha256(payload).hexdigest(),
        )

    def test_valid_cached_model_does_not_use_network(self):
        payload = b"model data"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test-model.bin"
            path.write_bytes(payload)
            with (
                patch.object(main.urllib.request, "urlopen") as urlopen,
                patch("sys.stdout", new_callable=StringIO),
            ):
                result = main.ensure_model(self.model_spec(payload), directory)

        self.assertEqual(result, path)
        urlopen.assert_not_called()

    def test_download_combines_bundled_and_system_certificates(self):
        payload = b"model data"
        context = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(main.certifi, "where", return_value="bundled-ca.pem"),
                patch.object(
                    main.ssl, "create_default_context", return_value=context
                ) as create_context,
                patch.object(
                    main.urllib.request, "urlopen", return_value=BytesIO(payload)
                ) as urlopen,
                patch("sys.stdout", new_callable=StringIO),
            ):
                main.ensure_model(self.model_spec(payload), directory)

        create_context.assert_called_once_with(cafile="bundled-ca.pem")
        context.load_default_certs.assert_called_once_with()
        self.assertIs(urlopen.call_args.kwargs["context"], context)

    def test_corrupt_cached_model_is_replaced_by_verified_download(self):
        payload = b"model data"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test-model.bin"
            path.write_bytes(b"corrupt")
            with (
                patch.object(
                    main.urllib.request, "urlopen", return_value=BytesIO(payload)
                ),
                patch("sys.stdout", new_callable=StringIO) as output,
            ):
                main.ensure_model(self.model_spec(payload), directory)

            self.assertEqual(path.read_bytes(), payload)
            self.assertIn("Rejected corrupted", output.getvalue())

    def test_interrupted_partial_download_restarts_cleanly(self):
        payload = b"model data"
        with tempfile.TemporaryDirectory() as directory:
            partial = Path(directory) / "test-model.bin.part"
            partial.write_bytes(b"old partial")
            with (
                patch.object(
                    main.urllib.request, "urlopen", return_value=BytesIO(payload)
                ),
                patch("sys.stdout", new_callable=StringIO) as output,
            ):
                main.ensure_model(self.model_spec(payload), directory)

            self.assertFalse(partial.exists())
            self.assertIn("Found an interrupted", output.getvalue())

    def test_bad_download_is_rejected(self):
        expected = b"model data"
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "test-model.bin"
            partial = Path(directory) / "test-model.bin.part"
            with (
                patch.object(
                    main.urllib.request, "urlopen", return_value=BytesIO(b"wrong data")
                ),
                patch("sys.stdout", new_callable=StringIO),
            ):
                with self.assertRaisesRegex(RuntimeError, "Rejected downloaded"):
                    main.ensure_model(self.model_spec(expected), directory)

            self.assertFalse(destination.exists())
            self.assertFalse(partial.exists())


class StartupErrorTest(unittest.TestCase):
    def test_frozen_double_click_keeps_startup_error_visible(self):
        with (
            patch.object(main.sys, "frozen", True, create=True),
            patch.object(main, "configure", side_effect=RuntimeError("test failure")),
            patch("builtins.input") as wait_for_enter,
            patch("sys.stdout", new_callable=StringIO),
        ):
            exit_code = main.main([])

        self.assertEqual(exit_code, 1)
        wait_for_enter.assert_called_once_with("Press Enter to close LocalFlow.")


class WhisperCppIntegrationTest(unittest.TestCase):
    @unittest.skipUnless(SAMPLE_PATH.is_file(), "Phase 1 sample is not installed")
    def test_transcribes_known_sample(self):
        transcript = main.transcribe_audio(load_sample_audio())

        self.assertIn("ask not what your country can do for you", transcript.lower())
        self.assertIsNone(main.active_native_process)

    def test_missing_runtime_has_clear_error(self):
        missing = Path(__file__).with_name("missing-whisper-cli.exe")
        with patch.object(main, "WHISPER_CLI", missing):
            with self.assertRaisesRegex(FileNotFoundError, "installation is incomplete"):
                main.transcribe_audio(np.ones(16_000, dtype=np.float32) * 0.1)

    def test_missing_model_has_clear_error(self):
        missing = Path(__file__).with_name("missing-whisper-model.bin")
        with patch.object(main, "WHISPER_MODEL", missing):
            with self.assertRaisesRegex(
                FileNotFoundError, "(?s)installation is incomplete.*missing-whisper-model"
            ):
                main.transcribe_audio(np.ones(16_000, dtype=np.float32) * 0.1)

    def test_silence_skips_transcription(self):
        self.assertEqual(main.transcribe_audio(np.zeros(16_000, dtype=np.float32)), "")

    def test_no_speech_does_not_run_cleanup(self):
        with (
            patch.object(main, "transcribe_audio", return_value=""),
            patch.object(main, "clean_text_locally") as cleanup,
            patch("sys.stdout", new_callable=StringIO),
        ):
            main.process_transcription(np.zeros(16_000, dtype=np.float32))
        cleanup.assert_not_called()

    def test_transcription_failure_returns_to_ready_state(self):
        main.app_state = main.ApplicationState.PROCESSING
        with (
            patch.object(main, "transcribe_audio", side_effect=RuntimeError("test failure")),
            patch("sys.stdout", new_callable=StringIO) as output,
        ):
            main.process_transcription(np.zeros(16_000, dtype=np.float32))

        self.assertIn("Transcription error: test failure", output.getvalue())
        self.assertIn("Ready!", output.getvalue())
        self.assertIs(main.app_state, main.ApplicationState.READY)


class S1MiniIntegrationTest(unittest.TestCase):
    @unittest.skipUnless(
        main.LLAMA_SERVER.is_file() and main.S1_MODEL.is_file(),
        "Phase 1 S1-mini runtime is not installed",
    )
    def test_cleans_known_transcript_locally(self):
        cleaned = main.clean_text_locally(S1_SAMPLE)

        self.assertEqual(cleaned, "So I need to send the report by Thursday.")
        self.assertIsNone(main.active_native_process)

    def test_missing_runtime_has_clear_error(self):
        missing = Path(__file__).with_name("missing-llama-server.exe")
        with patch.object(main, "LLAMA_SERVER", missing):
            with self.assertRaisesRegex(FileNotFoundError, "installation is incomplete"):
                main.clean_text_locally("hello")

    def test_missing_model_has_clear_error(self):
        missing = Path(__file__).with_name("missing-s1-model.gguf")
        with patch.object(main, "S1_MODEL", missing):
            with self.assertRaisesRegex(
                FileNotFoundError, "(?s)installation is incomplete.*missing-s1-model"
            ):
                main.clean_text_locally("hello")

    def test_output_limit_uses_recommended_approximation(self):
        raw_text = "a" * 400
        self.assertEqual(main.cleanup_token_limit(raw_text), 162)

    def test_cleanup_failure_copies_raw_transcript(self):
        raw_text = "raw transcript"
        with (
            patch.object(main, "transcribe_audio", return_value=raw_text),
            patch.object(main, "clean_text_locally", side_effect=RuntimeError("test failure")),
            patch.object(main.pyperclip, "copy") as copy,
            patch.object(main.keyboard, "send"),
            patch.object(main.time, "sleep"),
            patch("sys.stdout", new_callable=StringIO) as output,
        ):
            main.process_transcription(np.zeros(1, dtype=np.float32))

        copy.assert_called_once_with(raw_text)
        self.assertIn("Using the raw transcript instead.", output.getvalue())

    def test_empty_cleanup_result_is_valid(self):
        with (
            patch.object(main, "transcribe_audio", return_value="um uh"),
            patch.object(main, "clean_text_locally", return_value=""),
            patch.object(main.pyperclip, "copy") as copy,
            patch.object(main.keyboard, "send"),
            patch.object(main.time, "sleep"),
            patch("sys.stdout", new_callable=StringIO) as output,
        ):
            main.process_transcription(np.zeros(1, dtype=np.float32))

        copy.assert_called_once_with("")
        self.assertNotIn("Cleanup error", output.getvalue())


class OfflineOperationTest(unittest.TestCase):
    @unittest.skipUnless(
        SAMPLE_PATH.is_file()
        and main.WHISPER_CLI.is_file()
        and main.WHISPER_MODEL.is_file()
        and main.LLAMA_SERVER.is_file()
        and main.S1_MODEL.is_file(),
        "Local Phase 1 inference artifacts are not installed",
    )
    def test_full_pipeline_rejects_non_loopback_connections(self):
        main.app_state = main.ApplicationState.READY
        real_create_connection = socket.create_connection
        connections = []

        def loopback_only(address, *args, **kwargs):
            host = str(address[0]).lower()
            if host not in {"127.0.0.1", "::1", "localhost"}:
                raise AssertionError(f"External connection attempted: {address}")
            connections.append(address)
            return real_create_connection(address, *args, **kwargs)

        with patch.object(socket, "create_connection", new=loopback_only):
            raw_text = main.transcribe_audio(load_sample_audio())
            cleaned_text = main.clean_text_locally(raw_text)

        self.assertIn("ask not what your country can do for you", raw_text.lower())
        self.assertEqual(cleaned_text, raw_text)
        self.assertTrue(connections)


class HotkeyAndOutputTest(unittest.TestCase):
    def setUp(self):
        main.app_state = main.ApplicationState.READY
        main.pressed_key_codes.clear()
        main.hotkey_is_down = False
        main.AUTO_PASTE = False

    def send_key(self, event_type, key):
        scan_code = keyboard_codes(key)[0]
        main.handle_hotkey_event(
            SimpleNamespace(event_type=event_type, scan_code=scan_code)
        )

    def test_single_f23_starts_and_stops_once(self):
        _, modifiers, trigger = main.parse_hotkey("f23")
        main.hotkey_modifier_codes = modifiers
        main.hotkey_trigger_codes = trigger

        with (
            patch.object(main, "on_key_press") as press,
            patch.object(main, "on_key_release") as release,
        ):
            self.send_key(main.keyboard.KEY_DOWN, "f23")
            self.send_key(main.keyboard.KEY_DOWN, "f23")
            self.send_key(main.keyboard.KEY_UP, "f23")

        press.assert_called_once_with()
        release.assert_called_once_with()

    def test_combination_starts_on_trigger_and_ignores_repeat(self):
        _, modifiers, trigger = main.parse_hotkey("ctrl+shift+space")
        main.hotkey_modifier_codes = modifiers
        main.hotkey_trigger_codes = trigger

        with (
            patch.object(main, "on_key_press") as press,
            patch.object(main, "on_key_release") as release,
        ):
            self.send_key(main.keyboard.KEY_DOWN, "ctrl")
            self.send_key(main.keyboard.KEY_DOWN, "shift")
            press.assert_not_called()
            self.send_key(main.keyboard.KEY_DOWN, "space")
            self.send_key(main.keyboard.KEY_DOWN, "space")
            self.send_key(main.keyboard.KEY_UP, "space")

        press.assert_called_once_with()
        release.assert_called_once_with()

    def test_releasing_modifier_early_stops_and_cannot_restart_from_repeat(self):
        _, modifiers, trigger = main.parse_hotkey("ctrl+shift+space")
        main.hotkey_modifier_codes = modifiers
        main.hotkey_trigger_codes = trigger

        with (
            patch.object(main, "on_key_press") as press,
            patch.object(main, "on_key_release") as release,
        ):
            for key in ("ctrl", "shift", "space"):
                self.send_key(main.keyboard.KEY_DOWN, key)
            self.send_key(main.keyboard.KEY_UP, "shift")
            self.send_key(main.keyboard.KEY_DOWN, "shift")
            self.send_key(main.keyboard.KEY_DOWN, "space")
            self.send_key(main.keyboard.KEY_UP, "space")

        press.assert_called_once_with()
        release.assert_called_once_with()

    def test_invalid_combination_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "modifiers first"):
            main.parse_hotkey("ctrl+space+shift")

    def test_empty_hotkey_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "one or more key names"):
            main.parse_hotkey("")

    def test_invalid_hotkey_is_reported_at_startup(self):
        with (
            patch.object(main, "configure", side_effect=ValueError("bad hotkey")),
            patch("sys.stdout", new_callable=StringIO) as output,
        ):
            result = main.main()

        self.assertEqual(result, 1)
        self.assertIn("ERROR: bad hotkey", output.getvalue())

    def test_copy_without_automatic_paste(self):
        with (
            patch.object(main, "transcribe_audio", return_value="raw"),
            patch.object(main, "clean_text_locally", return_value="Clean."),
            patch.object(main.pyperclip, "copy") as copy,
            patch.object(main.keyboard, "send") as send,
            patch("sys.stdout", new_callable=StringIO),
        ):
            main.process_transcription(np.zeros(1, dtype=np.float32))

        copy.assert_called_once_with("Clean.")
        send.assert_not_called()

    def test_copy_and_automatic_paste_when_enabled(self):
        main.AUTO_PASTE = True
        with (
            patch.object(main, "transcribe_audio", return_value="raw"),
            patch.object(main, "clean_text_locally", return_value="Clean."),
            patch.object(main.pyperclip, "copy") as copy,
            patch.object(main.keyboard, "send") as send,
            patch.object(main.time, "sleep"),
            patch("sys.stdout", new_callable=StringIO),
        ):
            main.process_transcription(np.zeros(1, dtype=np.float32))

        copy.assert_called_once_with("Clean.")
        send.assert_called_once_with("ctrl+v")


class PipelineReliabilityTest(unittest.TestCase):
    def setUp(self):
        main.app_state = main.ApplicationState.READY
        main.audio_buffer.clear()
        main.recorded_samples = 0
        main.stream = None
        main.recording_timer = None
        main.worker_thread = None
        main.active_native_process = None
        main.AUTO_PASTE = False

    def tearDown(self):
        main.app_state = main.ApplicationState.READY
        main.audio_buffer.clear()
        main.recorded_samples = 0
        main.stream = None
        main.recording_timer = None
        main.worker_thread = None
        main.active_native_process = None
        main.AUTO_PASTE = False

    def test_only_one_recording_or_worker_can_run(self):
        audio_stream = MagicMock()
        timer = MagicMock()
        worker = MagicMock()
        samples = np.ones((main.MIN_RECORDING_SAMPLES, 1), dtype=np.float32)

        with (
            patch.object(main.sd, "InputStream", return_value=audio_stream) as open_stream,
            patch.object(main.threading, "Timer", return_value=timer),
            patch.object(main.threading, "Thread", return_value=worker),
            patch("sys.stdout", new_callable=StringIO) as output,
        ):
            main.on_key_press()
            self.assertIs(main.app_state, main.ApplicationState.RECORDING)
            main.audio_callback(samples, len(samples), None, None)
            main.on_key_release()
            self.assertIs(main.app_state, main.ApplicationState.PROCESSING)
            main.on_key_press()

        open_stream.assert_called_once()
        worker.start.assert_called_once_with()
        self.assertIn("Still processing; recording ignored.", output.getvalue())

    def test_audio_buffer_stops_growing_at_maximum_duration(self):
        main.app_state = main.ApplicationState.RECORDING
        main.recorded_samples = main.MAX_RECORDING_SAMPLES - 5
        samples = np.ones((10, 1), dtype=np.float32)

        main.audio_callback(samples, len(samples), None, None)
        main.audio_callback(samples, len(samples), None, None)

        self.assertEqual(main.recorded_samples, main.MAX_RECORDING_SAMPLES)
        self.assertEqual(sum(len(chunk) for chunk in main.audio_buffer), 5)

    def test_too_short_recording_is_ignored(self):
        main.app_state = main.ApplicationState.RECORDING
        main.recorded_samples = main.MIN_RECORDING_SAMPLES - 1
        main.audio_buffer.append(
            np.ones((main.recorded_samples, 1), dtype=np.float32)
        )
        main.stream = MagicMock()
        main.recording_timer = MagicMock()

        with (
            patch.object(main.threading, "Thread") as thread,
            patch("sys.stdout", new_callable=StringIO) as output,
        ):
            main.stop_recording()

        thread.assert_not_called()
        self.assertIs(main.app_state, main.ApplicationState.READY)
        self.assertIn("Recording too short", output.getvalue())

    def test_microphone_open_failure_returns_to_ready(self):
        with (
            patch.object(main.sd, "InputStream", side_effect=OSError("no input device")),
            patch("sys.stdout", new_callable=StringIO) as output,
        ):
            main.on_key_press()

        self.assertIs(main.app_state, main.ApplicationState.READY)
        self.assertIn("Microphone error: could not start recording", output.getvalue())

    def test_clipboard_failure_returns_to_ready(self):
        main.app_state = main.ApplicationState.PROCESSING
        with (
            patch.object(main, "transcribe_audio", return_value="raw"),
            patch.object(main, "clean_text_locally", return_value="Clean."),
            patch.object(main.pyperclip, "copy", side_effect=RuntimeError("clipboard busy")),
            patch("sys.stdout", new_callable=StringIO) as output,
        ):
            main.process_transcription(np.zeros(1, dtype=np.float32))

        self.assertIs(main.app_state, main.ApplicationState.READY)
        self.assertIn("Clipboard error: could not copy", output.getvalue())

    def test_shutdown_prevents_copy_and_paste(self):
        main.app_state = main.ApplicationState.PROCESSING
        main.AUTO_PASTE = True

        def clean_then_shutdown(raw_text):
            main.shutdown_application()
            return "Clean."

        with (
            patch.object(main, "transcribe_audio", return_value="raw"),
            patch.object(main, "clean_text_locally", side_effect=clean_then_shutdown),
            patch.object(main.pyperclip, "copy") as copy,
            patch.object(main.keyboard, "send") as send,
            patch.object(main.keyboard, "unhook_all"),
            patch("sys.stdout", new_callable=StringIO),
        ):
            main.process_transcription(np.zeros(1, dtype=np.float32))

        copy.assert_not_called()
        send.assert_not_called()
        self.assertIs(main.app_state, main.ApplicationState.SHUTTING_DOWN)

    def test_shutdown_terminates_active_native_process(self):
        process = MagicMock()
        process.poll.side_effect = [None, 0]
        main.app_state = main.ApplicationState.PROCESSING
        main.active_native_process = process

        with patch.object(main.keyboard, "unhook_all"):
            main.shutdown_application()

        process.terminate.assert_called_once_with()
        process.kill.assert_not_called()
        self.assertIs(main.app_state, main.ApplicationState.SHUTTING_DOWN)


def keyboard_codes(key):
    return main.keyboard.key_to_scan_codes(key)


if __name__ == "__main__":
    unittest.main()
