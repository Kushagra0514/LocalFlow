import threading
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

import numpy as np

from localflow.application import Application
from localflow.cloud import (
    CloudError,
    CloudErrorKind,
    CompletionResponse,
    ToolCall,
    ToolDefinition,
)
from localflow.commands import (
    COMMAND_SYSTEM_PROMPT,
    CommandHandler,
    build_command_handler,
)
from localflow.tools.open_app import OpenAppError
from localflow.pipeline import Pipeline
from localflow.types import ApplicationState, JobPurpose, Recording


class FakeClient:
    def __init__(self, response=None, error=None, callback=None):
        self.response = response or CompletionResponse(
            None, ToolCall("open_app", {"app_name": "Chrome"})
        )
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


class FakeRegistry:
    definitions = (
        ToolDefinition("open_app", "Open an app", {"type": "object"}),
    )

    def __init__(self, result="Chrome", error=None):
        self.result = result
        self.error = error
        self.calls = []

    def dispatch(self, call):
        self.calls.append(call)
        if self.error:
            raise self.error
        return self.result


class FakeTranscriber:
    active_process = None
    threads = 4

    def __init__(self, text="open chrome"):
        self.text = text
        self.calls = []
        self.cancel = MagicMock()
        self.kill = MagicMock()

    def transcribe(self, samples):
        self.calls.append(samples)
        return self.text


class CommandHandlerTest(unittest.TestCase):
    def test_disabled_mode_does_not_read_credentials(self):
        factory = MagicMock(side_effect=AssertionError("credential read"))
        handler = build_command_handler(
            False,
            "groq",
            "model",
            15,
            threading.Event(),
            client_factory=factory,
        )
        self.assertIsNone(handler)
        factory.assert_not_called()

    def test_missing_credentials_disables_only_command_mode(self):
        reports = []
        handler = build_command_handler(
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
        self.assertIsNone(handler)
        self.assertIn("unavailable (credentials)", reports[0])
        self.assertNotIn("private", reports[0])

    def test_aliases_are_passed_to_the_registry_without_changing_transport(self):
        registry = FakeRegistry()
        registry_factory = MagicMock(return_value=registry)
        reports = []
        shutdown = threading.Event()
        aliases = (("browser", "Google Chrome"),)
        handler = build_command_handler(
            True,
            "groq",
            "model",
            15,
            shutdown,
            aliases,
            client_factory=MagicMock(return_value=FakeClient()),
            registry_factory=registry_factory,
            report=reports.append,
        )
        self.assertIs(handler.registry, registry)
        registry_factory.assert_called_once_with(shutdown, aliases, reports.append)

    def test_success_makes_one_allowlisted_tool_request_and_has_no_output(self):
        client = FakeClient()
        registry = FakeRegistry()
        reports = []
        result = CommandHandler(client, registry, threading.Event(), reports.append)(
            "open chrome"
        )
        self.assertEqual(len(client.requests), 1)
        request = client.requests[0]
        self.assertEqual(request.messages[0].content, COMMAND_SYSTEM_PROMPT)
        self.assertEqual(request.messages[1].content, "open chrome")
        self.assertEqual(request.tools, registry.definitions)
        self.assertFalse(request.require_tool)
        self.assertEqual(len(registry.calls), 1)
        self.assertFalse(result.copy_to_clipboard)
        self.assertFalse(result.allow_auto_paste)
        self.assertEqual(reports, ["Opened Chrome."])

    def test_failures_copy_raw_command_without_allowing_paste(self):
        clients = (
            FakeClient(error=CloudError(CloudErrorKind.TIMEOUT, "private body")),
            FakeClient(error=RuntimeError("private transcript")),
        )
        for client in clients:
            reports = []
            with self.subTest(client=client):
                result = CommandHandler(
                    client, FakeRegistry(), threading.Event(), reports.append
                )(
                    "raw private command"
                )
                self.assertEqual(result.text, "raw private command")
                self.assertTrue(result.copy_to_clipboard)
                self.assertFalse(result.allow_auto_paste)
                self.assertNotIn("private", " ".join(reports))

    def test_missing_tool_call_is_a_no_action_success(self):
        registry = FakeRegistry()
        handler = CommandHandler(
            FakeClient(CompletionResponse("Not an app command.", None)),
            registry,
            threading.Event(),
            MagicMock(),
        )
        result = handler("tell me a joke")
        self.assertFalse(result.copy_to_clipboard)
        self.assertFalse(registry.calls)

    def test_validation_or_launch_failure_copies_raw_without_paste(self):
        registry = FakeRegistry(error=OpenAppError("Application was not found."))
        reports = []
        result = CommandHandler(
            FakeClient(), registry, threading.Event(), reports.append
        )("open missing")
        self.assertEqual(result.text, "open missing")
        self.assertTrue(result.copy_to_clipboard)
        self.assertFalse(result.allow_auto_paste)
        self.assertIn("not found", reports[0])

    def test_shutdown_before_and_during_request_prevents_output(self):
        shutdown = threading.Event()
        shutdown.set()
        client = FakeClient()
        registry = FakeRegistry()
        result = CommandHandler(client, registry, shutdown)("raw")
        self.assertFalse(client.requests)
        self.assertFalse(registry.calls)
        self.assertFalse(result.copy_to_clipboard)

        shutdown.clear()
        client = FakeClient(callback=shutdown.set)
        result = CommandHandler(client, registry, shutdown)("raw")
        self.assertEqual(len(client.requests), 1)
        self.assertFalse(registry.calls)
        self.assertFalse(result.copy_to_clipboard)


class CommandApplicationTest(unittest.TestCase):
    def test_command_uses_local_transcriber_once_and_success_has_no_output(self):
        transcriber = FakeTranscriber()
        client = FakeClient()
        command = CommandHandler(
            client, FakeRegistry(), threading.Event(), MagicMock()
        )
        dictation = MagicMock(side_effect=AssertionError("cleanup called"))
        publisher = MagicMock()
        app = Application(
            transcriber,
            Pipeline(
                {
                    JobPurpose.DICTATION: dictation,
                    JobPurpose.COMMAND: command,
                }
            ),
            {
                JobPurpose.DICTATION: "f23",
                JobPurpose.COMMAND: "ctrl+shift+.",
            },
            True,
            publisher=publisher,
        )
        app.state = ApplicationState.PROCESSING
        with patch("sys.stdout", new_callable=StringIO):
            app._process_recording(
                Recording(JobPurpose.COMMAND, np.ones(1, dtype=np.float32))
            )
        self.assertEqual(len(transcriber.calls), 1)
        self.assertEqual(len(client.requests), 1)
        dictation.assert_not_called()
        publisher.publish.assert_not_called()

    def test_failed_command_copies_raw_without_auto_paste(self):
        publisher = MagicMock()
        app = Application(
            FakeTranscriber(),
            Pipeline(
                {
                    JobPurpose.COMMAND: CommandHandler(
                        FakeClient(
                            error=CloudError(CloudErrorKind.SERVER, "private")
                        ),
                        FakeRegistry(),
                        threading.Event(),
                        MagicMock(),
                    )
                }
            ),
            {JobPurpose.COMMAND: "ctrl+shift+."},
            True,
            publisher=publisher,
        )
        app.state = ApplicationState.PROCESSING
        with patch("sys.stdout", new_callable=StringIO):
            app._process_recording(
                Recording(JobPurpose.COMMAND, np.ones(1, dtype=np.float32))
            )
        publisher.publish.assert_called_once_with("open chrome", False)


if __name__ == "__main__":
    unittest.main()
