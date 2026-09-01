import tempfile
import threading
import unittest
import wave
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from localflow import cloud
from localflow.application import Application
from localflow.cleanup import CloudCleanup
from localflow.cloud import (
    CloudError,
    CloudErrorKind,
    CompletionResponse,
    ToolCall,
)
from localflow.commands import CommandHandler
from localflow.pipeline import Pipeline, raw_dictation
from localflow.tools import Tool, ToolRegistry
from localflow.tools.open_app import (
    OPEN_APP_DEFINITION,
    AppCatalogue,
    AppEntry,
    OpenApp,
    validate_open_app,
)
from localflow.types import ApplicationState, JobPurpose, Recording
from localflow.whisper import read_pcm16_wav


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def complete(self, _request):
        if self.error:
            raise self.error
        return self.response


class FixedTranscriber:
    active_process = None
    threads = 4

    def __init__(self, expected_samples, text):
        self.expected_samples = expected_samples
        self.text = text

    def transcribe(self, samples):
        np.testing.assert_array_equal(samples, self.expected_samples)
        return self.text

    def cancel(self):
        pass

    def kill(self):
        pass


class ReleaseEndToEndTest(unittest.TestCase):
    def fixed_audio(self):
        pcm = np.array([0, 1000, -1000, 2000, -2000], dtype=np.int16)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fixed.wav"
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(pcm.tobytes())
            return read_pcm16_wav(path)

    def run_job(self, samples, raw_text, purpose, handler, publisher):
        shutdown = threading.Event()
        app = Application(
            FixedTranscriber(samples, raw_text),
            Pipeline({purpose: handler}),
            {purpose: "f23"},
            False,
            publisher=publisher,
            shutdown_event=shutdown,
        )
        app.state = ApplicationState.PROCESSING
        app._process_recording(Recording(purpose, samples))
        self.assertIs(app.state, ApplicationState.READY)

    def test_fixed_audio_cleanup_and_safe_command_matrix_is_offline(self):
        samples = self.fixed_audio()
        publisher = MagicMock()
        launcher = MagicMock()
        shutdown = threading.Event()
        catalogue = AppCatalogue(
            (AppEntry("Chrome", Path("chrome.lnk"), frozenset({"chrome"})),)
        )
        registry = ToolRegistry(
            (
                Tool(
                    OPEN_APP_DEFINITION,
                    validate_open_app,
                    OpenApp(catalogue, shutdown, start=launcher),
                ),
            )
        )

        with (
            patch.object(
                cloud.urllib.request,
                "urlopen",
                side_effect=AssertionError("external connection attempted"),
            ) as urlopen,
            patch("sys.stdout", new_callable=StringIO),
        ):
            self.run_job(
                samples,
                "local only",
                JobPurpose.DICTATION,
                raw_dictation,
                publisher,
            )
            publisher.publish.assert_called_with("local only", True)

            self.run_job(
                samples,
                "um hello there",
                JobPurpose.DICTATION,
                CloudCleanup(
                    FakeClient(CompletionResponse("Hello there.", None)),
                    threading.Event(),
                ),
                publisher,
            )
            publisher.publish.assert_called_with("Hello there.", True)

            self.run_job(
                samples,
                "raw fallback",
                JobPurpose.DICTATION,
                CloudCleanup(
                    FakeClient(
                        error=CloudError(CloudErrorKind.CONNECTION, "offline")
                    ),
                    threading.Event(),
                ),
                publisher,
            )
            publisher.publish.assert_called_with("raw fallback", True)

            self.run_job(
                samples,
                "open chrome",
                JobPurpose.COMMAND,
                CommandHandler(
                    FakeClient(
                        CompletionResponse(
                            None, ToolCall("open_app", {"app_name": "Chrome"})
                        )
                    ),
                    registry,
                    shutdown,
                ),
                publisher,
            )
            launcher.assert_called_once_with("chrome.lnk")

            self.run_job(
                samples,
                "open unsafe path",
                JobPurpose.COMMAND,
                CommandHandler(
                    FakeClient(
                        CompletionResponse(
                            None,
                            ToolCall("open_app", {"app_name": r"C:\\bad.exe"}),
                        )
                    ),
                    registry,
                    shutdown,
                ),
                publisher,
            )
            publisher.publish.assert_called_with("open unsafe path", False)
            launcher.assert_called_once()

            self.run_job(
                samples,
                "open chrome while offline",
                JobPurpose.COMMAND,
                CommandHandler(
                    FakeClient(
                        error=CloudError(CloudErrorKind.CONNECTION, "offline")
                    ),
                    registry,
                    shutdown,
                ),
                publisher,
            )
            publisher.publish.assert_called_with("open chrome while offline", False)
            launcher.assert_called_once()
            urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
