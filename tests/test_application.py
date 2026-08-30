import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

import numpy as np

import main
from localflow.application import Application
from localflow.pipeline import Pipeline, raw_dictation
from localflow.types import ApplicationState, JobPurpose, Recording


class FakeTranscriber:
    threads = 4
    active_process = None

    def __init__(self, text="raw"):
        self.text = text
        self.cancel = MagicMock()
        self.kill = MagicMock()
        self.validate_runtime = MagicMock()
        self.ensure_model = MagicMock()
        self.validate_installation = MagicMock()
        self.verify_runtime = MagicMock()

    def transcribe(self, samples):
        return self.text


class ApplicationTest(unittest.TestCase):
    def app(self, transcriber=None, publisher=None, thread_factory=None):
        return Application(
            transcriber or FakeTranscriber(),
            Pipeline({JobPurpose.DICTATION: raw_dictation}),
            "f23",
            False,
            publisher=publisher,
            thread_factory=thread_factory or MagicMock(),
        )

    def test_prepare_and_verify_delegate_to_transcriber(self):
        transcriber = FakeTranscriber()
        app = self.app(transcriber)
        app.prepare()
        app.verify_installation()
        transcriber.validate_runtime.assert_called_once_with()
        transcriber.ensure_model.assert_called_once_with()
        transcriber.validate_installation.assert_called_once_with()
        transcriber.verify_runtime.assert_called_once_with()

    def test_one_job_at_a_time(self):
        worker = MagicMock()
        app = self.app(thread_factory=MagicMock(return_value=worker))
        self.assertTrue(app._claim_recording(JobPurpose.DICTATION))
        app._accept_recording(
            Recording(JobPurpose.DICTATION, np.ones(10, dtype=np.float32))
        )
        with patch("sys.stdout", new_callable=StringIO) as output:
            self.assertFalse(app._claim_recording(JobPurpose.DICTATION))
        self.assertIs(app.state, ApplicationState.PROCESSING)
        worker.start.assert_called_once_with()
        self.assertIn("Still processing", output.getvalue())

    def test_worker_start_failure_returns_to_ready(self):
        worker = MagicMock()
        worker.start.side_effect = RuntimeError("cannot start")
        app = self.app(thread_factory=MagicMock(return_value=worker))
        app._claim_recording(JobPurpose.DICTATION)
        with patch("sys.stdout", new_callable=StringIO) as output:
            app._accept_recording(
                Recording(JobPurpose.DICTATION, np.ones(10, dtype=np.float32))
            )
        self.assertIs(app.state, ApplicationState.READY)
        self.assertIn("could not start the worker", output.getvalue())

    def test_replaceable_transcriber_pipeline_and_publisher(self):
        transcriber = FakeTranscriber("raw")
        publisher = MagicMock()
        pipeline = Pipeline({JobPurpose.DICTATION: lambda text: text.upper()})
        app = Application(transcriber, pipeline, "f23", False, publisher=publisher)
        app.state = ApplicationState.PROCESSING
        with patch("sys.stdout", new_callable=StringIO):
            app._process_recording(
                Recording(JobPurpose.DICTATION, np.ones(1, dtype=np.float32))
            )
        publisher.publish.assert_called_once_with("RAW")
        self.assertIs(app.state, ApplicationState.READY)

    def test_transcription_failure_returns_to_ready(self):
        transcriber = FakeTranscriber()
        transcriber.transcribe = MagicMock(side_effect=RuntimeError("test failure"))
        app = self.app(transcriber, publisher=MagicMock())
        app.state = ApplicationState.PROCESSING
        with patch("sys.stdout", new_callable=StringIO) as output:
            app._process_recording(
                Recording(JobPurpose.DICTATION, np.ones(1, dtype=np.float32))
            )
        self.assertIn("Transcription error: test failure", output.getvalue())
        self.assertIs(app.state, ApplicationState.READY)

    def test_empty_transcript_is_not_published(self):
        publisher = MagicMock()
        app = self.app(FakeTranscriber(""), publisher=publisher)
        app.state = ApplicationState.PROCESSING
        with patch("sys.stdout", new_callable=StringIO) as output:
            app._process_recording(
                Recording(JobPurpose.DICTATION, np.ones(1, dtype=np.float32))
            )
        publisher.publish.assert_not_called()
        self.assertIn("No speech detected", output.getvalue())
        self.assertIs(app.state, ApplicationState.READY)

    def test_microphone_failure_returns_application_to_ready(self):
        app = self.app()
        app.recorder.stream_factory = MagicMock(side_effect=OSError("no input device"))
        with patch("sys.stdout", new_callable=StringIO):
            app.recorder.start()
        self.assertIs(app.state, ApplicationState.READY)

    def test_shutdown_prevents_output_side_effect(self):
        transcriber = FakeTranscriber()
        app = self.app(transcriber)
        copy = MagicMock()
        app.publisher.copy = copy

        def transcribe_then_shutdown(_samples):
            app.shutdown()
            return "raw"

        transcriber.transcribe = transcribe_then_shutdown
        app.state = ApplicationState.PROCESSING
        with patch("sys.stdout", new_callable=StringIO):
            app._process_recording(
                Recording(JobPurpose.DICTATION, np.ones(1, dtype=np.float32))
            )
        copy.assert_not_called()
        self.assertIs(app.state, ApplicationState.SHUTTING_DOWN)

    def test_shutdown_closes_recorder_and_cancels_transcriber(self):
        transcriber = FakeTranscriber()
        app = self.app(transcriber)
        app.recorder.shutdown = MagicMock()
        app.shutdown()
        app.recorder.shutdown.assert_called_once_with()
        transcriber.cancel.assert_called_once_with()
        transcriber.kill.assert_called_once_with()


class BootstrapTest(unittest.TestCase):
    def test_frozen_double_click_keeps_startup_error_visible(self):
        with (
            patch.object(main.sys, "frozen", True, create=True),
            patch.object(main, "build_application", side_effect=RuntimeError("test failure")),
            patch("builtins.input") as wait_for_enter,
            patch("sys.stdout", new_callable=StringIO),
        ):
            exit_code = main.main([])
        self.assertEqual(exit_code, 1)
        wait_for_enter.assert_called_once_with("Press Enter to close LocalFlow.")

    def test_invalid_arguments_return_two(self):
        with patch("sys.stdout", new_callable=StringIO):
            self.assertEqual(main.main(["--unknown"]), 2)


if __name__ == "__main__":
    unittest.main()
