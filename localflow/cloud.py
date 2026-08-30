"""Provider-neutral cloud completion transport.

Feature prompts belong to cleanup and command handlers, not this module.
"""

import json
import os
import socket
import ssl
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

import certifi

from localflow import APP_VERSION

MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_COMPLETION_TOKENS = 4096


@dataclass(frozen=True)
class Message:
    role: str
    content: str


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters: Mapping[str, object]


@dataclass(frozen=True)
class CompletionRequest:
    messages: tuple[Message, ...]
    tools: tuple[ToolDefinition, ...] = ()
    require_tool: bool = False
    temperature: float = 0.0
    max_tokens: int = 512


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: Mapping[str, object]


@dataclass(frozen=True)
class CompletionResponse:
    text: str | None
    tool_call: ToolCall | None


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key_environment: str
    default_model: str
    headers: tuple[tuple[str, str], ...] = ()


PROVIDERS = {
    "groq": Provider(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_environment="GROQ_API_KEY",
        default_model="openai/gpt-oss-20b",
    )
}


class CloudErrorKind(Enum):
    CREDENTIALS = "credentials"
    INVALID_REQUEST = "invalid_request"
    REQUEST_TOO_LARGE = "request_too_large"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    TLS = "tls"
    DNS = "dns"
    CONNECTION = "connection"
    SERVER = "server"
    RESPONSE_TOO_LARGE = "response_too_large"
    MALFORMED_RESPONSE = "malformed_response"


class CloudError(RuntimeError):
    def __init__(self, kind: CloudErrorKind, message: str):
        self.kind = kind
        super().__init__(message)


def cloud_ssl_context():
    """Trust bundled current roots plus certificates managed by Windows."""
    context = ssl.create_default_context(cafile=certifi.where())
    context.load_default_certs()
    return context


def create_client(
    provider_name: str,
    model: str | None = None,
    timeout_seconds: int = 15,
    environment: Mapping[str, str] | None = None,
):
    try:
        provider = PROVIDERS[provider_name]
    except KeyError as error:
        raise CloudError(
            CloudErrorKind.INVALID_REQUEST,
            f"Unknown cloud provider {provider_name!r}.",
        ) from error
    environment = os.environ if environment is None else environment
    api_key = environment.get(provider.api_key_environment, "").strip()
    if not api_key:
        raise CloudError(
            CloudErrorKind.CREDENTIALS,
            f"Cloud features require the {provider.api_key_environment} environment variable.",
        )
    if not 1 <= timeout_seconds <= 120:
        raise CloudError(
            CloudErrorKind.INVALID_REQUEST,
            "Cloud timeout must be from 1 to 120 seconds.",
        )
    selected_model = model or provider.default_model
    if not selected_model.strip():
        raise CloudError(
            CloudErrorKind.INVALID_REQUEST,
            "Cloud model cannot be empty.",
        )
    return OpenAICompatibleClient(
        provider,
        api_key,
        selected_model,
        timeout_seconds,
    )


class OpenAICompatibleClient:
    def __init__(
        self,
        provider: Provider,
        api_key: str,
        model: str,
        timeout_seconds: int,
    ):
        self.provider = provider
        self._api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        payload = _encode_request(self.model, request)
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "User-Agent": f"LocalFlow/{APP_VERSION}",
            **dict(self.provider.headers),
        }
        http_request = urllib.request.Request(
            f"{self.provider.base_url}/chat/completions",
            data=payload,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                http_request,
                timeout=self.timeout_seconds,
                context=cloud_ssl_context(),
            ) as response:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except ValueError:
                        raise CloudError(
                            CloudErrorKind.MALFORMED_RESPONSE,
                            "The cloud provider returned an invalid response.",
                        ) from None
                    if declared_length < 0:
                        raise CloudError(
                            CloudErrorKind.MALFORMED_RESPONSE,
                            "The cloud provider returned an invalid response.",
                        )
                    if declared_length > MAX_RESPONSE_BYTES:
                        raise CloudError(
                            CloudErrorKind.RESPONSE_TOO_LARGE,
                            "The cloud provider response was too large.",
                        )
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except CloudError:
            raise
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
            raise _http_error(status) from None
        except urllib.error.URLError as error:
            raise _connection_error(error.reason) from None
        except (TimeoutError, socket.timeout):
            raise CloudError(
                CloudErrorKind.TIMEOUT,
                "The cloud provider request timed out.",
            ) from None
        except ssl.SSLError:
            raise CloudError(
                CloudErrorKind.TLS,
                "Could not establish a secure connection to the cloud provider.",
            ) from None
        except (OSError, ValueError):
            raise CloudError(
                CloudErrorKind.CONNECTION,
                "Could not connect to the cloud provider.",
            ) from None
        if len(body) > MAX_RESPONSE_BYTES:
            raise CloudError(
                CloudErrorKind.RESPONSE_TOO_LARGE,
                "The cloud provider response was too large.",
            )
        return _decode_response(body)


def _encode_request(model: str, request: CompletionRequest) -> bytes:
    if not request.messages:
        raise CloudError(
            CloudErrorKind.INVALID_REQUEST,
            "A cloud completion requires at least one message.",
        )
    if request.require_tool and not request.tools:
        raise CloudError(
            CloudErrorKind.INVALID_REQUEST,
            "A required tool completion must include a tool definition.",
        )
    if not 0 <= request.temperature <= 2:
        raise CloudError(
            CloudErrorKind.INVALID_REQUEST,
            "Cloud completion temperature must be from 0 to 2.",
        )
    if not 1 <= request.max_tokens <= MAX_COMPLETION_TOKENS:
        raise CloudError(
            CloudErrorKind.INVALID_REQUEST,
            f"Cloud max_tokens must be from 1 to {MAX_COMPLETION_TOKENS}.",
        )
    messages = []
    for message in request.messages:
        if (
            message.role not in {"system", "user", "assistant"}
            or not isinstance(message.content, str)
        ):
            raise CloudError(
                CloudErrorKind.INVALID_REQUEST,
                "Cloud messages require a valid role and text content.",
            )
        messages.append({"role": message.role, "content": message.content})

    data = {
        "model": model,
        "messages": messages,
        "temperature": request.temperature,
        "max_completion_tokens": request.max_tokens,
        "stream": False,
    }
    if request.tools:
        data["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in request.tools
        ]
        data["tool_choice"] = "required" if request.require_tool else "auto"
        data["parallel_tool_calls"] = False
    try:
        payload = json.dumps(
            data, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise CloudError(
            CloudErrorKind.INVALID_REQUEST,
            "The cloud completion request is not JSON-compatible.",
        ) from None
    if len(payload) > MAX_REQUEST_BYTES:
        raise CloudError(
            CloudErrorKind.REQUEST_TOO_LARGE,
            "The cloud completion request was too large.",
        )
    return payload


def _decode_response(body: bytes) -> CompletionResponse:
    try:
        data = json.loads(body.decode("utf-8"))
        choices = data["choices"]
        if not isinstance(choices, list) or len(choices) != 1:
            raise TypeError
        message = choices[0]["message"]
        text = message.get("content")
        if text is not None and not isinstance(text, str):
            raise TypeError
        tool_calls = message.get("tool_calls") or []
        if not isinstance(tool_calls, list) or len(tool_calls) > 1:
            raise TypeError
        tool_call = None
        if tool_calls:
            if tool_calls[0].get("type") != "function":
                raise TypeError
            function = tool_calls[0]["function"]
            name = function["name"]
            arguments = json.loads(function["arguments"])
            if not isinstance(name, str) or not name or not isinstance(arguments, dict):
                raise TypeError
            tool_call = ToolCall(name, arguments)
    except (KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise CloudError(
            CloudErrorKind.MALFORMED_RESPONSE,
            "The cloud provider returned an invalid response.",
        ) from None
    return CompletionResponse(text, tool_call)


def _http_error(status: int) -> CloudError:
    if status == 401:
        return CloudError(
            CloudErrorKind.AUTHENTICATION,
            "The cloud provider rejected the API key.",
        )
    if status == 403:
        return CloudError(
            CloudErrorKind.PERMISSION,
            "The cloud provider denied this request.",
        )
    if status == 429:
        return CloudError(
            CloudErrorKind.RATE_LIMIT,
            "The cloud provider rate limit was reached.",
        )
    if status == 413:
        return CloudError(
            CloudErrorKind.REQUEST_TOO_LARGE,
            "The cloud provider rejected the request as too large.",
        )
    if status in {424, 498} or status >= 500:
        return CloudError(
            CloudErrorKind.SERVER,
            "The cloud provider is temporarily unavailable.",
        )
    return CloudError(
        CloudErrorKind.INVALID_REQUEST,
        "The cloud provider rejected the request.",
    )


def _connection_error(reason: object) -> CloudError:
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return CloudError(
            CloudErrorKind.TIMEOUT,
            "The cloud provider request timed out.",
        )
    if isinstance(reason, ssl.SSLError):
        return CloudError(
            CloudErrorKind.TLS,
            "Could not establish a secure connection to the cloud provider.",
        )
    if isinstance(reason, socket.gaierror):
        return CloudError(
            CloudErrorKind.DNS,
            "Could not find the cloud provider on the network.",
        )
    return CloudError(
        CloudErrorKind.CONNECTION,
        "Could not connect to the cloud provider.",
    )
