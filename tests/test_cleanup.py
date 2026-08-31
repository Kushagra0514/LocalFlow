import threading
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

import numpy as np

from localflow.cleanup import (
    CLEANUP_SYSTEM_PROMPT,
    CloudCleanup,
    build_cleanup_handler,
)
from localflow import cloud
from localflow.cloud import (
    CloudError,
    CloudErrorKind,
    CompletionResponse,
    ToolCall,
)
from localflow.application import Application
from localflow.output import OutputPublisher
from localflow.pipeline import Pipeline, raw_dictation
from localflow.types import ApplicationState, JobPurpose, Recording


class FakeClient:
    def __init__(self, response=None, error=None, callback=None):
        self.response = response or CompletionResponse("Clean text.", None)
        self.error = error
        self.callback = callback
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        if self.callback:
            self.callback()
        if self.error:
            raise self.error
        return self.response


class FakeTranscriber:
    active_process = None
    threads = 4

    def __init__(self, text="raw text"):
        self.text = text

    def transcribe(self, _samples):
        return self.text

    def cancel(self):
        pass

    def kill(self):
        pass


class CleanupHandlerTest(unittest.TestCase):
    def test_disabled_cleanup_is_identity_without_client_or_credentials(self):
        client_factory = MagicMock(side_effect=AssertionError("credential read"))
        handler = build_cleanup_handler(
            False,
            "groq",
            "model",
            15,
            threading.Event(),
            client_factory=client_factory,
        )
        self.assertIs(handler, raw_dictation)
        self.assertEqual(handler("raw text"), "raw text")
        client_factory.assert_not_called()

    def test_enabled_cleanup_sends_only_prompt_and_raw_text(self):
        client = FakeClient(CompletionResponse("  Clean text.  ", None))
        handler = build_cleanup_handler(
            True,
            "groq",
            "model",
            15,
            threading.Event(),
            client_factory=MagicMock(return_value=client),
            report=MagicMock(),
        )
        self.assertEqual(handler("raw text"), "Clean text.")
        request = client.requests[0]
        self.assertEqual(len(request.messages), 2)
        self.assertEqual(request.messages[0].content, CLEANUP_SYSTEM_PROMPT)
        self.assertEqual(request.messages[1].role, "user")
        self.assertEqual(request.messages[1].content, "raw text")
        self.assertEqual(request.temperature, 0)
        self.assertFalse(request.tools)

    def test_missing_credentials_does_not_prevent_raw_dictation(self):
        reports = []
        handler = build_cleanup_handler(
            True,
            "groq",
            "model",
            15,
            threading.Event(),
            client_factory=MagicMock(
                side_effect=CloudError(
                    CloudErrorKind.CREDENTIALS, "private credential detail"
                )
            ),
            report=reports.append,
        )
        self.assertIs(handler, raw_dictation)
        self.assertEqual(handler("raw text"), "raw text")
        self.assertIn("unavailable (credentials)", reports[0])
        self.assertNotIn("private", reports[0])

    def test_failure_empty_text_and_tool_call_preserve_raw_text(self):
        cases = (
            FakeClient(
                error=CloudError(
                    CloudErrorKind.TIMEOUT, "private transcript and provider body"
                )
            ),
            FakeClient(
                error=CloudError(
                    CloudErrorKind.MALFORMED_RESPONSE, "private provider body"
                )
            ),
            FakeClient(
                error=CloudError(
                    CloudErrorKind.RESPONSE_TOO_LARGE, "private provider body"
                )
            ),
            FakeClient(error=RuntimeError("private transcript")),
            FakeClient(CompletionResponse("", None)),
            FakeClient(CompletionResponse("   ", None)),
            FakeClient(CompletionResponse(None, None)),
            FakeClient(CompletionResponse(None, ToolCall("unexpected", {}))),
        )
        for client in cases:
            reports = []
            handler = CloudCleanup(client, threading.Event(), reports.append)
            with self.subTest(client=client):
                self.assertEqual(handler("raw private transcript"), "raw private transcript")
                self.assertNotIn("private", " ".join(reports))

    def test_shutdown_before_and_during_request_discards_cleanup(self):
        shutdown = threading.Event()
        shutdown.set()
        client = FakeClient()
        self.assertEqual(CloudCleanup(client, shutdown)("raw"), "raw")
        self.assertFalse(client.requests)

        shutdown.clear()
        client = FakeClient(callback=shutdown.set)
        self.assertEqual(CloudCleanup(client, shutdown)("raw"), "raw")
        self.assertEqual(len(client.requests), 1)


class CleanupApplicationTest(unittest.TestCase):
    def app(self, client, auto_paste=False, copy=None, paste=None):
        shutdown = threading.Event()
        publisher = OutputPublisher(
            auto_paste,
            shutdown,
            threading.Lock(),
            copy=copy or MagicMock(),
            paste=paste or MagicMock(),
            delay=lambda _seconds: None,
        )
        app = Application(
            FakeTranscriber(),
            Pipeline({JobPurpose.DICTATION: CloudCleanup(client, shutdown)}),
            "f23",
            auto_paste,
            publisher=publisher,
            shutdown_event=shutdown,
        )
        app.state = ApplicationState.PROCESSING
        return app, publisher

    def process(self, app):
        app._process_recording(
            Recording(JobPurpose.DICTATION, np.ones(1, dtype=np.float32))
        )

    def test_cleanup_success_copies_and_optionally_pastes_clean_text(self):
        copy = MagicMock()
        paste = MagicMock()
        app, _ = self.app(FakeClient(), auto_paste=True, copy=copy, paste=paste)
        with patch("sys.stdout", new_callable=StringIO):
            self.process(app)
        copy.assert_called_once_with("Clean text.")
        paste.assert_called_once_with()
        self.assertIs(app.state, ApplicationState.READY)

    def test_cleanup_disabled_dictation_is_offline(self):
        copy = MagicMock()
        shutdown = threading.Event()
        publisher = OutputPublisher(
            False,
            shutdown,
            threading.Lock(),
            copy=copy,
        )
        app = Application(
            FakeTranscriber(),
            Pipeline({JobPurpose.DICTATION: raw_dictation}),
            "f23",
            False,
            publisher=publisher,
            shutdown_event=shutdown,
        )
        app.state = ApplicationState.PROCESSING
        with (
            patch.object(
                cloud.urllib.request,
                "urlopen",
                side_effect=AssertionError("external connection attempted"),
            ) as urlopen,
            patch("sys.stdout", new_callable=StringIO),
        ):
            self.process(app)
        copy.assert_called_once_with("raw text")
        urlopen.assert_not_called()

    def test_cleanup_failure_publishes_raw_text(self):
        copy = MagicMock()
        client = FakeClient(
            error=CloudError(CloudErrorKind.SERVER, "private provider response")
        )
        app, publisher = self.app(client, copy=copy)
        with patch("sys.stdout", new_callable=StringIO) as output:
            self.process(app)
        copy.assert_called_once_with("raw text")
        publisher.paste.assert_not_called()
        self.assertNotIn("private provider", output.getvalue())
        self.assertIs(app.state, ApplicationState.READY)

    def test_clipboard_failure_after_cleanup_returns_to_ready(self):
        app, _ = self.app(
            FakeClient(), copy=MagicMock(side_effect=RuntimeError("clipboard busy"))
        )
        with patch("sys.stdout", new_callable=StringIO) as output:
            self.process(app)
        self.assertIn("Clipboard error", output.getvalue())
        self.assertIs(app.state, ApplicationState.READY)

    def test_shutdown_during_request_prevents_copy_and_paste(self):
        copy = MagicMock()
        paste = MagicMock()
        app, _ = self.app(FakeClient(), auto_paste=True, copy=copy, paste=paste)
        app.pipeline.handlers[JobPurpose.DICTATION].client.callback = app.shutdown
        with patch("sys.stdout", new_callable=StringIO):
            self.process(app)
        copy.assert_not_called()
        paste.assert_not_called()
        self.assertIs(app.state, ApplicationState.SHUTTING_DOWN)


if __name__ == "__main__":
    unittest.main()
