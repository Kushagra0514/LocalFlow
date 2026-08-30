import hashlib
import os
import tempfile
import unittest
import wave
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from localflow import whisper

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / ".local" / "phase1"
SAMPLE_PATH = FIXTURE_ROOT / "samples" / "jfk.wav"
TRANSCRIBER = whisper.WhisperTranscriber(
    FIXTURE_ROOT / "whisper" / "Release" / "whisper-cli.exe",
    FIXTURE_ROOT / "models",
)


def load_sample_audio():
    with wave.open(str(SAMPLE_PATH), "rb") as wav_file:
        audio = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype="<i2")
    return audio.astype(np.float32) / 32_768


class ModelManagementTest(unittest.TestCase):
    @staticmethod
    def model_spec(payload=b"model data"):
        return whisper.ModelSpec(
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
                patch.object(whisper.urllib.request, "urlopen") as urlopen,
                patch("sys.stdout", new_callable=StringIO),
            ):
                result = whisper.ensure_model(self.model_spec(payload), Path(directory))
        self.assertEqual(result, path)
        urlopen.assert_not_called()

    def test_download_combines_bundled_and_system_certificates(self):
        payload = b"model data"
        context = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            with (
                patch.object(whisper.certifi, "where", return_value="bundled-ca.pem"),
                patch.object(
                    whisper.ssl, "create_default_context", return_value=context
                ) as create_context,
                patch.object(
                    whisper.urllib.request, "urlopen", return_value=BytesIO(payload)
                ) as urlopen,
                patch("sys.stdout", new_callable=StringIO),
            ):
                whisper.ensure_model(self.model_spec(payload), Path(directory))
        create_context.assert_called_once_with(cafile="bundled-ca.pem")
        context.load_default_certs.assert_called_once_with()
        self.assertIs(urlopen.call_args.kwargs["context"], context)

    def test_corrupt_cached_model_is_replaced(self):
        payload = b"model data"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test-model.bin"
            path.write_bytes(b"corrupt")
            with (
                patch.object(
                    whisper.urllib.request, "urlopen", return_value=BytesIO(payload)
                ),
                patch("sys.stdout", new_callable=StringIO) as output,
            ):
                whisper.ensure_model(self.model_spec(payload), Path(directory))
            self.assertEqual(path.read_bytes(), payload)
            self.assertIn("Rejected corrupted", output.getvalue())

    def test_interrupted_partial_download_restarts(self):
        payload = b"model data"
        with tempfile.TemporaryDirectory() as directory:
            partial = Path(directory) / "test-model.bin.part"
            partial.write_bytes(b"old partial")
            with (
                patch.object(
                    whisper.urllib.request, "urlopen", return_value=BytesIO(payload)
                ),
                patch("sys.stdout", new_callable=StringIO) as output,
            ):
                whisper.ensure_model(self.model_spec(payload), Path(directory))
            self.assertFalse(partial.exists())
            self.assertIn("Found an interrupted", output.getvalue())

    def test_bad_download_is_rejected(self):
        expected = b"model data"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(
                    whisper.urllib.request,
                    "urlopen",
                    return_value=BytesIO(b"wrong data"),
                ),
                patch("sys.stdout", new_callable=StringIO),
            ):
                with self.assertRaisesRegex(RuntimeError, "Rejected downloaded"):
                    whisper.ensure_model(self.model_spec(expected), root)
            self.assertFalse((root / "test-model.bin").exists())
            self.assertFalse((root / "test-model.bin.part").exists())


class WhisperTranscriberTest(unittest.TestCase):
    def test_missing_runtime_has_clear_error(self):
        transcriber = whisper.WhisperTranscriber(
            Path("missing-whisper-cli.exe"), Path("models")
        )
        with self.assertRaisesRegex(FileNotFoundError, "packaged native runtimes"):
            transcriber.validate_runtime()

    def test_missing_model_has_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "whisper-cli.exe"
            executable.touch()
            transcriber = whisper.WhisperTranscriber(executable, Path(directory))
            with self.assertRaisesRegex(
                FileNotFoundError, "(?s)installation is incomplete.*ggml-base"
            ):
                transcriber.validate_installation()

    def test_silence_skips_native_process(self):
        transcriber = whisper.WhisperTranscriber(Path("missing"), Path("missing"))
        self.assertEqual(transcriber.transcribe(np.zeros(16_000, dtype=np.float32)), "")

    def test_cancel_terminates_active_process(self):
        transcriber = whisper.WhisperTranscriber(Path("x"), Path("x"))
        process = MagicMock()
        process.poll.return_value = None
        transcriber._process = process
        transcriber.cancel()
        process.terminate.assert_called_once_with()

    @unittest.skipUnless(
        SAMPLE_PATH.is_file()
        and TRANSCRIBER.executable.is_file()
        and TRANSCRIBER.model_path.is_file(),
        "Source-tree Whisper fixtures are not installed",
    )
    def test_transcribes_known_sample_without_network(self):
        with patch.object(
            whisper.urllib.request,
            "urlopen",
            side_effect=AssertionError("network request attempted"),
        ):
            transcript = TRANSCRIBER.transcribe(load_sample_audio())
        self.assertIn("ask not what your country can do for you", transcript.lower())
        self.assertIsNone(TRANSCRIBER.active_process)


if __name__ == "__main__":
    unittest.main()

