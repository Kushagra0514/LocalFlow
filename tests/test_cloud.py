import json
import socket
import ssl
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from unittest.mock import MagicMock, patch

from localflow import cloud


TEXT_RESPONSE = {
    "choices": [{"message": {"role": "assistant", "content": "Clean text."}}]
}
TOOL_RESPONSE = {
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "type": "function",
                        "function": {
                            "name": "open_app",
                            "arguments": '{"app_name":"Chrome"}',
                        },
                    }
                ],
            }
        }
    ]
}


class Response(BytesIO):
    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = headers or {}


class ProviderContractMixin:
    def test_text_response_is_normalized(self):
        result = self.client.complete(
            cloud.CompletionRequest((cloud.Message("user", "dictation"),))
        )
        self.assertEqual(result, cloud.CompletionResponse("Clean text.", None))

    def test_single_tool_call_is_normalized(self):
        tool = cloud.ToolDefinition(
            "open_app",
            "Open an installed application.",
            {
                "type": "object",
                "properties": {"app_name": {"type": "string"}},
                "required": ["app_name"],
                "additionalProperties": False,
            },
        )
        result = self.client.complete(
            cloud.CompletionRequest(
                (cloud.Message("user", "tool"),),
                tools=(tool,),
                require_tool=True,
            )
        )
        self.assertEqual(result.text, None)
        self.assertEqual(result.tool_call.name, "open_app")
        self.assertEqual(result.tool_call.arguments, {"app_name": "Chrome"})


class LocalProviderHandler(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        request = json.loads(self.rfile.read(length))
        type(self).requests.append((self.path, self.headers, request))
        content = request["messages"][-1]["content"]
        response = TOOL_RESPONSE if content == "tool" else TEXT_RESPONSE
        body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


class LocalProviderContractTest(ProviderContractMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        LocalProviderHandler.requests = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), LocalProviderHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.provider = cloud.Provider(
            "fake", f"http://{host}:{port}/v1", "FAKE_API_KEY", "fake-model"
        )
        cls.provider_patch = patch.dict(cloud.PROVIDERS, {"fake": cls.provider})
        cls.provider_patch.start()
        cls.client = cloud.create_client(
            "fake", environment={"FAKE_API_KEY": "test-key"}
        )

    @classmethod
    def tearDownClass(cls):
        cls.provider_patch.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_request_uses_openai_contract_without_streaming(self):
        self.client.complete(
            cloud.CompletionRequest(
                (
                    cloud.Message("system", "instructions"),
                    cloud.Message("user", "dictation"),
                ),
                temperature=0,
                max_tokens=100,
            )
        )
        path, headers, request = LocalProviderHandler.requests[-1]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer test-key")
        self.assertEqual(request["model"], "fake-model")
        self.assertEqual(request["temperature"], 0)
        self.assertEqual(request["max_completion_tokens"], 100)
        self.assertIs(request["stream"], False)

    def test_tool_request_disables_parallel_calls(self):
        tool = cloud.ToolDefinition("open_app", "Open an app.", {"type": "object"})
        self.client.complete(
            cloud.CompletionRequest(
                (cloud.Message("user", "tool"),),
                tools=(tool,),
                require_tool=True,
            )
        )
        request = LocalProviderHandler.requests[-1][2]
        self.assertEqual(request["tool_choice"], "required")
        self.assertIs(request["parallel_tool_calls"], False)


class CloudClientTest(unittest.TestCase):
    def client(self):
        return cloud.create_client(
            "groq", environment={"GROQ_API_KEY": "top-secret-key"}
        )

    def test_groq_registry_is_trusted_and_has_no_user_endpoint(self):
        provider = cloud.PROVIDERS["groq"]
        self.assertEqual(provider.base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(provider.api_key_environment, "GROQ_API_KEY")
        self.assertEqual(provider.default_model, "openai/gpt-oss-20b")

    def test_missing_credentials_and_unknown_provider_are_safe(self):
        with self.assertRaises(cloud.CloudError) as missing:
            cloud.create_client("groq", environment={})
        self.assertEqual(missing.exception.kind, cloud.CloudErrorKind.CREDENTIALS)
        with self.assertRaises(cloud.CloudError) as unknown:
            cloud.create_client("other", environment={})
        self.assertEqual(unknown.exception.kind, cloud.CloudErrorKind.INVALID_REQUEST)

    def test_bundled_and_windows_certificate_roots_are_used(self):
        context = MagicMock()
        with (
            patch.object(cloud.certifi, "where", return_value="bundled.pem"),
            patch.object(
                cloud.ssl, "create_default_context", return_value=context
            ) as create_context,
        ):
            self.assertIs(cloud.cloud_ssl_context(), context)
        create_context.assert_called_once_with(cafile="bundled.pem")
        context.load_default_certs.assert_called_once_with()

    def test_request_is_bounded_before_network_access(self):
        request = cloud.CompletionRequest(
            (cloud.Message("user", "x" * cloud.MAX_REQUEST_BYTES),)
        )
        with (
            patch.object(cloud.urllib.request, "urlopen") as urlopen,
            self.assertRaises(cloud.CloudError) as raised,
        ):
            self.client().complete(request)
        self.assertEqual(raised.exception.kind, cloud.CloudErrorKind.REQUEST_TOO_LARGE)
        urlopen.assert_not_called()

    def test_response_size_is_bounded(self):
        response = Response(b"{}", {"Content-Length": str(cloud.MAX_RESPONSE_BYTES + 1)})
        with (
            patch.object(cloud.urllib.request, "urlopen", return_value=response),
            self.assertRaises(cloud.CloudError) as raised,
        ):
            self.client().complete(
                cloud.CompletionRequest((cloud.Message("user", "text"),))
            )
        self.assertEqual(raised.exception.kind, cloud.CloudErrorKind.RESPONSE_TOO_LARGE)

        response = Response(b"x" * (cloud.MAX_RESPONSE_BYTES + 1))
        with (
            patch.object(cloud.urllib.request, "urlopen", return_value=response),
            self.assertRaises(cloud.CloudError) as raised,
        ):
            self.client().complete(
                cloud.CompletionRequest((cloud.Message("user", "text"),))
            )
        self.assertEqual(raised.exception.kind, cloud.CloudErrorKind.RESPONSE_TOO_LARGE)

    def test_malformed_responses_are_normalized_without_body_disclosure(self):
        secret_body = b'{"private_transcript":"do not disclose"}'
        with (
            patch.object(
                cloud.urllib.request, "urlopen", return_value=Response(secret_body)
            ),
            self.assertRaises(cloud.CloudError) as raised,
        ):
            self.client().complete(
                cloud.CompletionRequest((cloud.Message("user", "private transcript"),))
            )
        self.assertEqual(raised.exception.kind, cloud.CloudErrorKind.MALFORMED_RESPONSE)
        self.assertNotIn("private", str(raised.exception))
        self.assertNotIn("do not disclose", str(raised.exception))

    def test_multiple_or_malformed_tool_calls_are_rejected(self):
        malformed_calls = (
            [TOOL_RESPONSE, TOOL_RESPONSE],
            [{"type": "unknown", "function": {"name": "x", "arguments": "{}"}}],
        )
        for tool_calls in malformed_calls:
            malformed = {
                "choices": [{"message": {"content": None, "tool_calls": tool_calls}}]
            }
            with (
                self.subTest(tool_calls=tool_calls),
                patch.object(
                    cloud.urllib.request,
                    "urlopen",
                    return_value=Response(json.dumps(malformed).encode()),
                ),
                self.assertRaises(cloud.CloudError) as raised,
            ):
                self.client().complete(
                    cloud.CompletionRequest((cloud.Message("user", "tool"),))
                )
            self.assertEqual(
                raised.exception.kind, cloud.CloudErrorKind.MALFORMED_RESPONSE
            )

    def test_http_failures_are_categorized_without_retries_or_details(self):
        cases = {
            400: cloud.CloudErrorKind.INVALID_REQUEST,
            401: cloud.CloudErrorKind.AUTHENTICATION,
            403: cloud.CloudErrorKind.PERMISSION,
            413: cloud.CloudErrorKind.REQUEST_TOO_LARGE,
            429: cloud.CloudErrorKind.RATE_LIMIT,
            498: cloud.CloudErrorKind.SERVER,
            503: cloud.CloudErrorKind.SERVER,
        }
        for status, kind in cases.items():
            with self.subTest(status=status):
                error = urllib.error.HTTPError(
                    "https://trusted.invalid",
                    status,
                    "top-secret-key private transcript",
                    {},
                    BytesIO(b"raw provider body"),
                )
                with (
                    patch.object(
                        cloud.urllib.request, "urlopen", side_effect=error
                    ) as urlopen,
                    self.assertRaises(cloud.CloudError) as raised,
                ):
                    self.client().complete(
                        cloud.CompletionRequest((cloud.Message("user", "private"),))
                    )
                self.assertEqual(raised.exception.kind, kind)
                self.assertEqual(urlopen.call_count, 1)
                self.assertNotIn("secret", str(raised.exception))
                self.assertNotIn("transcript", str(raised.exception))
                self.assertNotIn("raw provider", str(raised.exception))

    def test_network_timeout_tls_and_dns_are_categorized(self):
        cases = (
            (TimeoutError(), cloud.CloudErrorKind.TIMEOUT),
            (ssl.SSLError(), cloud.CloudErrorKind.TLS),
            (socket.gaierror(), cloud.CloudErrorKind.DNS),
            (OSError("private transcript"), cloud.CloudErrorKind.CONNECTION),
        )
        for reason, kind in cases:
            with (
                self.subTest(kind=kind),
                patch.object(
                    cloud.urllib.request,
                    "urlopen",
                    side_effect=urllib.error.URLError(reason),
                ),
                self.assertRaises(cloud.CloudError) as raised,
            ):
                self.client().complete(
                    cloud.CompletionRequest((cloud.Message("user", "private"),))
                )
            self.assertEqual(raised.exception.kind, kind)
            self.assertNotIn("private", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
