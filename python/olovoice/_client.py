"""Synchronous and asynchronous clients for the olovoice Public API."""

from __future__ import annotations

import asyncio
import ipaddress
import math
import os
import re
import threading
import time
import weakref
from collections.abc import Mapping as ABCMapping
from concurrent.futures import Future
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import (
    Callable,
    Dict,
    Coroutine,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    TypeVar,
    Union,
    cast,
)
from urllib.parse import quote, urlsplit

import httpx

from ._errors import APIConnectionError, InvalidResponseError, OloVoiceError, error_from_status
from ._types import (
    AssistantBackgroundAudio,
    AssistantObjectResponse,
    AssistantStatus,
    AssistantSttConfig,
    CallBackgroundAudio,
    CallSttConfig,
    ConversationConfig,
    CreateAssistantResponse,
    CreateCallResponse,
    CreateLeadResponse,
    CreateWebCallResponse,
    Customer,
    DeleteAssistantResponse,
    GetCallLogResponse,
    InlineTool,
    JSONObject,
    JSONValue,
    ListAssistantsResponse,
    ListCallLogsResponse,
    MetricsRange,
    MetricsResponse,
    PredefinedFunctionsConfig,
    PrivacyConfig,
    RecordingUrlResponse,
    RuntimeLlmInput,
    RuntimeTtsInput,
    UpdateAssistantResponse,
    WebCustomer,
)

__version__ = "0.1.0"

_DEFAULT_BASE_URL = "https://api.olovoice.ai"
_DEFAULT_TIMEOUT = 30.0
_DEFAULT_MAX_RETRIES = 2
_MAX_RETRY_DELAY_SECONDS = 60.0
_MAX_ERROR_TEXT_CHARS = 2048
_MAX_REDIRECT_LOCATION_CHARS = 512
_MAX_RESPONSE_BODY_BYTES = 2 * 1024 * 1024
_CAMEL_CASE_FIELD = re.compile(r"^[a-z][A-Za-z0-9]*$")
_PROTECTED_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "authorization",
        "connection",
        "content-length",
        "content-type",
        "cookie",
        "host",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "user-agent",
    }
)
_OPENAI_REALTIME_PROVIDERS = frozenset(
    {"openai-realtime", "openai_realtime", "openai.realtime"}
)
_OPENAI_REALTIME_MODELS = frozenset(
    {"gpt-realtime", "gpt-realtime-1.5", "gpt-realtime-2"}
)
_NATIVE_AUDIO_MODES = frozenset(
    {"native", "native-audio", "nativeaudio", "speech-to-speech", "s2s"}
)
_SUPPORTED_LLM_PROVIDERS = frozenset(
    {
        "openai",
        "openai_realtime",
        "openai-realtime",
        "openai.realtime",
        "google",
        "gemini",
        "anthropic",
        "aws",
        "amazon",
        "bedrock",
        "groq",
        "groq.ai",
        "groqai",
        "qwen",
    }
)
_SUPPORTED_TTS_PROVIDERS = frozenset(
    {
        "aws",
        "amazon",
        "elevenlabs",
        "eleven",
        "freya",
        "freyavoice",
        "nova",
        "novaforge",
        "nova-tts",
        "openai",
        "polly",
    }
)
_AWS_TTS_PROVIDERS = frozenset({"aws", "amazon", "polly"})
_DEFAULTED_TTS_PROVIDERS = frozenset(
    {"freya", "freyavoice", "nova", "novaforge", "nova-tts"}
)
_FULL_TTS_PROVIDERS = frozenset({"elevenlabs", "eleven", "openai"})
_AWS_TTS_MODELS = frozenset(
    {
        "standard",
        "polly-standard",
        "neural",
        "polly-neural",
        "generative",
        "polly-generative",
        "long-form",
        "longform",
        "polly-long-form",
    }
)
_SUPPORTED_STT_PROVIDERS = frozenset(
    {
        "azure",
        "azure_speech",
        "azure-speech",
        "aws",
        "amazon",
        "transcribe",
        "transcribe-streaming",
        "deepgram",
        "dg",
        "elevenlabs",
        "eleven",
        "eleven-labs",
        "freya",
        "freyavoice",
        "groq",
        "groq.ai",
        "groqai",
        "nova",
        "novaforge",
        "nova-stt",
        "openai",
        "whisper",
    }
)
_PHONE_NUMBER = re.compile(r"^\+?[0-9]{6,20}$")

QueryValue = Union[str, int, float, bool]
Query = Mapping[str, Optional[QueryValue]]
RequestBody = Dict[str, object]
_ResultT = TypeVar("_ResultT")


class _NotGiven:
    __slots__ = ()

    def __repr__(self) -> str:
        return "NOT_GIVEN"


_NOT_GIVEN = _NotGiven()
UpdateString = Union[str, None, _NotGiven]
UpdateBool = Union[bool, _NotGiven]
UpdateLlmConfig = Union[RuntimeLlmInput, None, _NotGiven]
UpdateTtsConfig = Union[RuntimeTtsInput, None, _NotGiven]
UpdateSttConfig = Union[AssistantSttConfig, None, _NotGiven]
UpdateConversationConfig = Union[ConversationConfig, None, _NotGiven]
UpdateBackgroundAudioConfig = Union[AssistantBackgroundAudio, None, _NotGiven]
UpdatePrivacyConfig = Union[PrivacyConfig, None, _NotGiven]
UpdatePredefinedFunctionsConfig = Union[
    PredefinedFunctionsConfig, None, _NotGiven
]
UpdateStrings = Union[Sequence[str], _NotGiven]


_CALL_FIELDS = frozenset(
    {
        "assistantId",
        "squadId",
        "workflowId",
        "phoneNumberId",
        "customer",
        "firstMessage",
        "content",
        "serverUrl",
        "llm",
        "tts",
        "stt",
        "conversation",
        "backgroundAudio",
        "privacy",
        "predefinedFunctions",
        "tools",
        "toolIds",
        "structuredOutputIds",
        "fileIds",
        "extras",
        "pronunciationLibraryId",
    }
)
_WEB_CALL_FIELDS = frozenset(
    {
        "organizationId",
        "assistantId",
        "squadId",
        "workflowId",
        "customer",
        "firstMessage",
        "content",
        "serverUrl",
        "llm",
        "tts",
        "stt",
        "conversation",
        "backgroundAudio",
        "privacy",
        "predefinedFunctions",
        "tools",
        "toolIds",
        "structuredOutputIds",
        "fileIds",
        "extras",
    }
)
_ASSISTANT_FIELDS = frozenset(
    {
        "name",
        "status",
        "firstMessage",
        "content",
        "isActive",
        "serverUrl",
        "folderId",
        "llm",
        "tts",
        "stt",
        "conversation",
        "backgroundAudio",
        "privacy",
        "predefinedFunctions",
        "toolIds",
        "structuredOutputIds",
        "knowledgeFileIds",
        "usePronunciationLibrary",
        "pronunciationLibraryId",
    }
)
_LEAD_FIELDS = frozenset(
    {"name", "phone", "email", "metadata", "categoryId", "campaignId"}
)


def _clean_query(params: Query) -> Dict[str, QueryValue]:
    return {key: value for key, value in params.items() if value is not None}


def _bounded_text(value: str, limit: int = _MAX_ERROR_TEXT_CHARS) -> str:
    compact = value.strip()
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _deadline_error(
    timeout: float, response: Optional[httpx.Response] = None
) -> APIConnectionError:
    return APIConnectionError(
        f"Request timed out after {timeout:g}s",
        status=response.status_code if response is not None else None,
        request_id=_request_id(response) if response is not None else None,
        retry_after=(
            _retry_after_seconds(response) if response is not None else None
        ),
    )


def _remaining_or_raise(
    deadline: float,
    timeout: float,
    response: Optional[httpx.Response] = None,
) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise _deadline_error(timeout, response)
    return remaining


def _set_response_read_timeout(response: httpx.Response, remaining: float) -> None:
    extension = cast(object, response.request.extensions.get("timeout"))
    if isinstance(extension, dict):
        timeout_values = cast(Dict[str, Optional[float]], extension)
        timeout_values["read"] = remaining


def _decode_body(
    response: httpx.Response, deadline: float, timeout: float
) -> object:
    _remaining_or_raise(deadline, timeout, response)
    if not response.content or not response.content.strip():
        return None
    try:
        result = cast(object, response.json())
    except (ValueError, RecursionError):
        result = _bounded_text(response.text)
    _remaining_or_raise(deadline, timeout, response)
    return result


def _response_too_large_error(
    response: httpx.Response, preview: bytes = b""
) -> InvalidResponseError:
    text_preview = _bounded_text(preview.decode("utf-8", errors="replace"))
    return InvalidResponseError(
        f"Response body exceeded {_MAX_RESPONSE_BODY_BYTES} bytes",
        status=response.status_code,
        body=text_preview,
        request_id=_request_id(response),
        retry_after=_retry_after_seconds(response),
    )


def _declared_response_too_large(response: httpx.Response) -> bool:
    value = response.headers.get("content-length")
    if value is None:
        return False
    try:
        return int(value) > _MAX_RESPONSE_BODY_BYTES
    except ValueError:
        return False


def _reject_compressed_response(response: httpx.Response) -> None:
    content_encoding = response.headers.get("content-encoding")
    if content_encoding is None or content_encoding.strip().casefold() == "identity":
        return
    raise InvalidResponseError(
        "Compressed response bodies are refused to enforce the decoded body limit",
        status=response.status_code,
        body=None,
        request_id=_request_id(response),
        retry_after=_retry_after_seconds(response),
    )


async def _buffer_async_response(
    response: httpx.Response, deadline: float, timeout: float
) -> httpx.Response:
    remaining = _remaining_or_raise(deadline, timeout, response)
    _set_response_read_timeout(response, remaining)
    _reject_compressed_response(response)
    if _declared_response_too_large(response):
        raise _response_too_large_error(response)
    chunks: List[bytes] = []
    size = 0
    iterator = response.aiter_bytes().__aiter__()
    while True:
        remaining = _remaining_or_raise(deadline, timeout, response)
        _set_response_read_timeout(response, remaining)
        try:
            chunk = await asyncio.wait_for(
                iterator.__anext__(), timeout=remaining
            )
        except StopAsyncIteration:
            break
        except asyncio.TimeoutError as exc:
            error = _deadline_error(timeout, response)
            error.__cause__ = exc
            raise error
        _remaining_or_raise(deadline, timeout, response)
        size += len(chunk)
        if size > _MAX_RESPONSE_BODY_BYTES:
            preview = (b"".join(chunks) + chunk)[:_MAX_ERROR_TEXT_CHARS]
            raise _response_too_large_error(response, preview)
        chunks.append(chunk)
    _remaining_or_raise(deadline, timeout, response)
    headers = response.headers.copy()
    for name in ("content-encoding", "content-length", "transfer-encoding"):
        if name in headers:
            del headers[name]
    return httpx.Response(
        response.status_code,
        headers=headers,
        content=b"".join(chunks),
        request=response.request,
        extensions=response.extensions,
    )


def _request_id(response: httpx.Response) -> Optional[str]:
    value: object = response.headers.get("x-request-id")
    return value if isinstance(value, str) else None


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    value = raw.strip()
    if value.isascii() and value.isdigit():
        try:
            seconds = float(value)
        except (OverflowError, ValueError):
            return None
        return seconds if math.isfinite(seconds) else None
    try:
        target = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())


def _error_for_response(
    response: httpx.Response, deadline: float, timeout: float
) -> OloVoiceError:
    body = _decode_body(response, deadline, timeout)
    request_id = _request_id(response)
    retry_after = _retry_after_seconds(response)

    if 300 <= response.status_code < 400:
        location = _bounded_text(
            response.headers.get("location", ""), _MAX_REDIRECT_LOCATION_CHARS
        )
        destination = f" to {location}" if location else ""
        return InvalidResponseError(
            f"Redirect response refused (HTTP {response.status_code}){destination}",
            status=response.status_code,
            body=body,
            request_id=request_id,
            retry_after=retry_after,
        )

    message: Optional[str] = None
    if isinstance(body, dict):
        mapping = cast(Mapping[str, object], body)
        for key in ("error", "message"):
            candidate = mapping.get(key)
            if isinstance(candidate, str) and candidate.strip():
                message = _bounded_text(candidate)
                break
    elif isinstance(body, str) and body:
        message = body

    return error_from_status(
        response.status_code,
        message or f"HTTP {response.status_code}",
        body,
        request_id,
        retry_after,
    )


def _success_object(
    response: httpx.Response, deadline: float, timeout: float
) -> JSONObject:
    body = _decode_body(response, deadline, timeout)
    if isinstance(body, dict):
        return cast(JSONObject, body)
    if body is None:
        message = f"Expected a JSON object but HTTP {response.status_code} returned an empty body"
    else:
        message = f"Expected a JSON object but HTTP {response.status_code} returned non-object content"
    raise InvalidResponseError(
        message,
        status=response.status_code,
        body=_bounded_text(response.text),
        request_id=_request_id(response),
    )


def _resolve_api_key(api_key: Optional[str]) -> str:
    key = api_key if api_key is not None else os.environ.get("OLOVOICE_API_KEY")
    if not isinstance(key, str) or not key.strip():
        raise ValueError(
            "olovoice: missing API key. Pass api_key= or set the "
            "OLOVOICE_API_KEY environment variable."
        )
    if key != key.strip():
        raise ValueError("olovoice: API key must not contain surrounding whitespace.")
    return key


def _is_loopback(hostname: str) -> bool:
    if hostname.casefold() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _validate_base_url(
    base_url: str,
    *,
    dangerously_allow_custom_base_url: bool,
    dangerously_allow_insecure_http: bool,
) -> str:
    if not isinstance(base_url, str) or not base_url or base_url != base_url.strip():
        raise ValueError("olovoice: base_url must be a non-empty URL without whitespace.")
    if not isinstance(dangerously_allow_custom_base_url, bool):
        raise TypeError("dangerously_allow_custom_base_url must be a bool.")
    if not isinstance(dangerously_allow_insecure_http, bool):
        raise TypeError("dangerously_allow_insecure_http must be a bool.")

    parsed = urlsplit(base_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("olovoice: base_url contains an invalid port.") from exc
    hostname = parsed.hostname
    scheme = parsed.scheme.casefold()
    if scheme not in {"https", "http"} or hostname is None:
        raise ValueError("olovoice: base_url must be an absolute HTTP(S) URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("olovoice: base_url must not contain userinfo.")
    if parsed.query or parsed.fragment:
        raise ValueError("olovoice: base_url must not contain a query or fragment.")
    if parsed.path not in {"", "/"}:
        raise ValueError("olovoice: base_url path prefixes are not supported.")

    canonical = (
        scheme == "https"
        and hostname.casefold() == "api.olovoice.ai"
        and port in {None, 443}
    )
    if not canonical and not dangerously_allow_custom_base_url:
        raise ValueError(
            "olovoice: custom base_url requires "
            "dangerously_allow_custom_base_url=True."
        )
    if scheme == "http":
        if not dangerously_allow_insecure_http:
            raise ValueError(
                "olovoice: HTTP requires dangerously_allow_insecure_http=True."
            )
        if not _is_loopback(hostname):
            raise ValueError("olovoice: insecure HTTP is allowed only for loopback hosts.")
    return base_url.rstrip("/")


def _validate_options(timeout: float, max_retries: int) -> Tuple[float, int]:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
        raise TypeError("timeout must be a positive finite number.")
    normalized_timeout = float(timeout)
    if not math.isfinite(normalized_timeout) or normalized_timeout <= 0:
        raise ValueError("timeout must be a positive finite number.")
    if isinstance(max_retries, bool) or not isinstance(max_retries, int):
        raise TypeError("max_retries must be a non-negative integer.")
    if max_retries < 0:
        raise ValueError("max_retries must be a non-negative integer.")
    return normalized_timeout, max_retries


def _build_headers(
    api_key: str, default_headers: Optional[Mapping[str, str]]
) -> httpx.Headers:
    headers = httpx.Headers(
        {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "User-Agent": f"olovoice-python/{__version__}",
        }
    )
    for name, value in (default_headers or {}).items():
        if not isinstance(name, str) or not isinstance(value, str):
            raise TypeError("default_headers keys and values must be strings.")
        if name.casefold() in _PROTECTED_HEADERS:
            raise ValueError(f"olovoice: default_headers may not override {name!r}.")
        headers[name] = value
    return headers


def _backoff_seconds(attempt: int) -> float:
    exponent = min(max(attempt - 1, 0), 16)
    return min(_MAX_RETRY_DELAY_SECONDS, 0.5 * (2.0**exponent))


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    retry_after = _retry_after_seconds(response)
    if retry_after is not None:
        return min(_MAX_RETRY_DELAY_SECONDS, retry_after)
    return _backoff_seconds(attempt)


def _retry_delay_for_error(error: OloVoiceError, attempt: int) -> float:
    if error.retry_after is not None:
        return min(_MAX_RETRY_DELAY_SECONDS, error.retry_after)
    return _backoff_seconds(attempt)


def _classify_transport_error(
    error: APIConnectionError,
    response: Optional[httpx.Response],
) -> Tuple[OloVoiceError, bool]:
    if response is None or response.is_success:
        return error, True
    status = response.status_code
    request_id = _request_id(response)
    retry_after = _retry_after_seconds(response)
    if 300 <= status < 400:
        location = _bounded_text(
            response.headers.get("location", ""), _MAX_REDIRECT_LOCATION_CHARS
        )
        destination = f" to {location}" if location else ""
        return (
            InvalidResponseError(
                f"Redirect response refused (HTTP {status}){destination}",
                status=status,
                body=error.body,
                request_id=request_id,
                retry_after=retry_after,
            ),
            False,
        )
    typed_error = error_from_status(
        status,
        str(error),
        error.body,
        request_id,
        retry_after,
    )
    return typed_error, status == 429 or status >= 500


def _classify_protocol_error(
    error: InvalidResponseError,
    response: Optional[httpx.Response],
) -> Tuple[OloVoiceError, bool]:
    if response is None or response.is_success:
        return error, False
    status = response.status_code
    if 300 <= status < 400:
        connection_error = APIConnectionError(
            str(error),
            status=status,
            body=error.body,
            request_id=error.request_id,
            retry_after=error.retry_after,
        )
        return _classify_transport_error(connection_error, response)
    typed_error = error_from_status(
        status,
        str(error),
        error.body,
        error.request_id or _request_id(response),
        error.retry_after,
    )
    return typed_error, status == 429 or status >= 500


def _require_nonempty(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string.")
    return value.strip()


def _optional_nonempty(value: Optional[str], name: str) -> Optional[str]:
    return None if value is None else _require_nonempty(value, name)


def _mapping(value: Mapping[str, object], name: str) -> Dict[str, object]:
    if not isinstance(value, ABCMapping):
        raise TypeError(f"{name} must be a mapping.")
    return dict(value)


def _call_customer(value: Customer) -> Dict[str, object]:
    customer = _mapping(cast(Mapping[str, object], value), "customer")
    number = customer.get("number")
    if not isinstance(number, str) or not number.strip():
        raise ValueError("customer.number must be a non-empty string.")
    normalized_number = re.sub(r"\s+", "", number.strip())
    if _PHONE_NUMBER.fullmatch(normalized_number) is None:
        raise ValueError("customer.number must contain 6-20 digits with an optional +.")
    name = customer.get("name")
    if name is not None and not isinstance(name, str):
        raise TypeError("customer.name must be a string when provided.")
    return customer


def _provider_config(
    value: Mapping[str, object],
    name: str,
    *,
    supported: frozenset[str],
    require_model: bool = False,
    require_voice_id: bool = False,
) -> Dict[str, object]:
    config = _mapping(value, name)
    provider = config.get("provider")
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError(f"{name}.provider must be a non-empty string.")
    if provider.strip().casefold() not in supported:
        raise ValueError(f"{name}.provider {provider!r} is not supported.")
    if require_model:
        model = config.get("model")
        if not isinstance(model, str) or not model.strip():
            raise ValueError(f"{name}.model must be a non-empty string.")
    if require_voice_id:
        voice_id = config.get("voiceId")
        if not isinstance(voice_id, str) or not voice_id.strip():
            raise ValueError(f"{name}.voiceId must be a non-empty string.")
    return config


def _llm_config(value: Mapping[str, object], name: str = "llm") -> Dict[str, object]:
    return _provider_config(
        value,
        name,
        supported=_SUPPORTED_LLM_PROVIDERS,
        require_model=True,
    )


def _tts_config(value: Mapping[str, object], name: str = "tts") -> Dict[str, object]:
    config = _provider_config(
        value,
        name,
        supported=_SUPPORTED_TTS_PROVIDERS,
    )
    provider_value = config["provider"]
    provider = cast(str, provider_value).strip().casefold()
    model = config.get("model")
    voice_id = config.get("voiceId")
    requires_model = provider in _FULL_TTS_PROVIDERS
    requires_voice_id = provider in _FULL_TTS_PROVIDERS or provider in _AWS_TTS_PROVIDERS
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise ValueError(f"{name}.model must be a non-empty string when provided.")
    if voice_id is not None and (
        not isinstance(voice_id, str) or not voice_id.strip()
    ):
        raise ValueError(f"{name}.voiceId must be a non-empty string when provided.")
    if requires_model and model is None:
        raise ValueError(f"{name}.model must be a non-empty string.")
    if requires_voice_id and voice_id is None:
        raise ValueError(f"{name}.voiceId must be a non-empty string.")
    if (
        provider in _AWS_TTS_PROVIDERS
        and isinstance(model, str)
        and model.strip().casefold() not in _AWS_TTS_MODELS
    ):
        raise ValueError(f"{name}.model {model!r} is not supported for AWS Polly.")
    if provider not in _DEFAULTED_TTS_PROVIDERS | _FULL_TTS_PROVIDERS | _AWS_TTS_PROVIDERS:
        raise ValueError(f"{name}.provider {provider_value!r} is not supported.")
    return config


def _call_stt_config(
    value: Mapping[str, object], name: str = "stt"
) -> Dict[str, object]:
    config = _mapping(value, name)
    provider = config.get("provider")
    if provider is None:
        return config
    if not isinstance(provider, str) or not provider.strip():
        raise ValueError(f"{name}.provider must be a non-empty string when provided.")
    if provider.strip().casefold() not in _SUPPORTED_STT_PROVIDERS:
        raise ValueError(f"{name}.provider {provider!r} is not supported.")
    return config


def _classify_openai_realtime(config: Mapping[str, object]) -> Tuple[bool, bool]:
    provider_value = config.get("provider")
    model_value = config.get("model")
    provider = provider_value.strip().casefold() if isinstance(provider_value, str) else ""
    model = model_value.strip().casefold() if isinstance(model_value, str) else ""
    active = provider in _OPENAI_REALTIME_PROVIDERS or (
        provider == "openai" and model in _OPENAI_REALTIME_MODELS
    )
    if not active:
        return False, False
    mode_value = config.get("realtimeMode")
    mode = mode_value.strip().casefold().replace("_", "-") if isinstance(mode_value, str) else ""
    return True, mode in _NATIVE_AUDIO_MODES


def _assistant_stt_config(
    value: Mapping[str, object], name: str = "stt"
) -> Dict[str, object]:
    config = _provider_config(
        value, name, supported=_SUPPORTED_STT_PROVIDERS
    )
    for field in ("keywords", "keywordBoosts"):
        raw_keywords = config.get(field)
        if raw_keywords is None:
            continue
        if not isinstance(raw_keywords, list):
            raise TypeError(f"{name}.{field} must be a list of keyword objects.")
        for keyword in raw_keywords:
            if not isinstance(keyword, ABCMapping):
                raise TypeError(
                    f"{name}.{field} entries must be objects with phrase and boost."
                )
            keyword_mapping = cast(Mapping[str, object], keyword)
            phrase = keyword_mapping.get("phrase")
            boost = keyword_mapping.get("boost")
            if not isinstance(phrase, str) or not phrase.strip():
                raise ValueError(
                    f"{name}.{field} entries require a non-empty phrase."
                )
            if boost is not None and (
                isinstance(boost, bool)
                or not isinstance(boost, (int, float))
                or not math.isfinite(float(boost))
            ):
                raise ValueError(f"{name}.{field} entries require a finite boost.")
    return config


def _assistant_background_audio_config(
    value: Mapping[str, object], name: str = "background_audio"
) -> Dict[str, object]:
    config = _mapping(value, name)
    for field in ("ambient", "thinking"):
        clip = config.get(field)
        if clip is None:
            continue
        if field == "ambient" and isinstance(clip, str):
            if not clip.strip():
                raise ValueError(f"{name}.ambient must not be an empty string.")
            continue
        if not isinstance(clip, ABCMapping):
            raise TypeError(f"{name}.{field} must be a clip object or None.")
        clip_mapping = cast(Mapping[str, object], clip)
        builtin = clip_mapping.get("builtin")
        volume = clip_mapping.get("volume")
        if builtin is not None and not isinstance(builtin, str):
            raise TypeError(f"{name}.{field}.builtin must be a string or None.")
        if volume is not None and (
            isinstance(volume, bool)
            or not isinstance(volume, (int, float))
            or not math.isfinite(float(volume))
        ):
            raise TypeError(f"{name}.{field}.volume must be a finite number or None.")
    return config


def _strings(value: Sequence[str], name: str) -> List[str]:
    if isinstance(value, (str, bytes)):
        raise TypeError(f"{name} must be a sequence of strings.")
    result = list(value)
    if any(not isinstance(item, str) or not item.strip() for item in result):
        raise ValueError(f"{name} must contain only non-empty strings.")
    return result


def _tools(value: Sequence[InlineTool]) -> List[Dict[str, object]]:
    if isinstance(value, (str, bytes)):
        raise TypeError("tools must be a sequence of mappings.")
    return [_mapping(cast(Mapping[str, object], item), "tools item") for item in value]


def _forward_fields(
    extra_fields: Mapping[str, JSONValue], reserved: frozenset[str]
) -> RequestBody:
    result: RequestBody = {}
    for name, value in extra_fields.items():
        if name in reserved:
            raise TypeError(
                f"{name!r} is a reserved API field; use its snake_case argument instead."
            )
        if "_" in name or _CAMEL_CASE_FIELD.fullmatch(name) is None:
            raise TypeError(
                f"Forward-compatible extra field {name!r} must be a lower camelCase name."
            )
        result[name] = value
    return result


def _put(body: RequestBody, key: str, value: object) -> None:
    if value is not None:
        body[key] = value


def _build_call_body(
    *,
    phone_number_id: str,
    customer: Customer,
    llm: RuntimeLlmInput,
    conversation: ConversationConfig,
    background_audio: CallBackgroundAudio,
    assistant_id: Optional[str],
    squad_id: Optional[str],
    workflow_id: Optional[str],
    first_message: Optional[str],
    content: Optional[str],
    server_url: Optional[str],
    tts: Optional[RuntimeTtsInput],
    stt: Optional[CallSttConfig],
    privacy: Optional[PrivacyConfig],
    predefined_functions: Optional[PredefinedFunctionsConfig],
    tools: Optional[Sequence[InlineTool]],
    tool_ids: Optional[Sequence[str]],
    structured_output_ids: Optional[Sequence[str]],
    file_ids: Optional[Sequence[str]],
    extras: Optional[JSONObject],
    pronunciation_library_id: Optional[str],
    extra_fields: Mapping[str, JSONValue],
) -> RequestBody:
    assistant = _optional_nonempty(assistant_id, "assistant_id")
    squad = _optional_nonempty(squad_id, "squad_id")
    workflow = _optional_nonempty(workflow_id, "workflow_id")
    if not any((assistant, squad, workflow)):
        raise ValueError("One of assistant_id, squad_id, or workflow_id is required.")
    if assistant and not squad and not workflow:
        _require_nonempty(first_message or "", "first_message")
        _require_nonempty(content or "", "content")

    llm_config = _llm_config(llm)
    realtime_active, native_audio = _classify_openai_realtime(llm_config)
    if not native_audio and tts is None:
        raise ValueError("tts is required unless llm.realtimeMode is 'nativeAudio'.")
    if not realtime_active and stt is None:
        raise ValueError("stt is required unless an llm realtimeMode is active.")

    body = _forward_fields(extra_fields, _CALL_FIELDS)
    body.update(
        {
            "phoneNumberId": _require_nonempty(phone_number_id, "phone_number_id"),
            "customer": _call_customer(customer),
            "llm": llm_config,
            "conversation": _mapping(conversation, "conversation"),
            "backgroundAudio": _mapping(background_audio, "background_audio"),
        }
    )
    _put(body, "assistantId", assistant)
    _put(body, "squadId", squad)
    _put(body, "workflowId", workflow)
    _put(body, "firstMessage", first_message)
    _put(body, "content", content)
    _put(body, "serverUrl", server_url)
    if tts is not None:
        body["tts"] = _tts_config(tts)
    if stt is not None:
        body["stt"] = _call_stt_config(stt)
    if privacy is not None:
        body["privacy"] = _mapping(privacy, "privacy")
    if predefined_functions is not None:
        body["predefinedFunctions"] = _mapping(
            predefined_functions, "predefined_functions"
        )
    if tools is not None:
        body["tools"] = _tools(tools)
    if tool_ids is not None:
        body["toolIds"] = _strings(tool_ids, "tool_ids")
    if structured_output_ids is not None:
        body["structuredOutputIds"] = _strings(
            structured_output_ids, "structured_output_ids"
        )
    if file_ids is not None:
        body["fileIds"] = _strings(file_ids, "file_ids")
    if extras is not None:
        body["extras"] = _mapping(extras, "extras")
    _put(body, "pronunciationLibraryId", pronunciation_library_id)
    return body


def _build_web_call_body(
    *,
    organization_id: str,
    assistant_id: Optional[str],
    squad_id: Optional[str],
    workflow_id: Optional[str],
    customer: Optional[WebCustomer],
    first_message: Optional[str],
    content: Optional[str],
    server_url: Optional[str],
    llm: Optional[RuntimeLlmInput],
    tts: Optional[RuntimeTtsInput],
    stt: Optional[CallSttConfig],
    conversation: Optional[ConversationConfig],
    background_audio: Optional[CallBackgroundAudio],
    privacy: Optional[PrivacyConfig],
    predefined_functions: Optional[PredefinedFunctionsConfig],
    tools: Optional[Sequence[InlineTool]],
    structured_output_ids: Optional[Sequence[str]],
    file_ids: Optional[Sequence[str]],
    extras: Optional[JSONObject],
    extra_fields: Mapping[str, JSONValue],
) -> RequestBody:
    assistant = _optional_nonempty(assistant_id, "assistant_id")
    squad = _optional_nonempty(squad_id, "squad_id")
    workflow = _optional_nonempty(workflow_id, "workflow_id")
    if not any((assistant, squad, workflow)):
        raise ValueError("One of assistant_id, squad_id, or workflow_id is required.")
    body = _forward_fields(extra_fields, _WEB_CALL_FIELDS)
    body["organizationId"] = _require_nonempty(organization_id, "organization_id")
    _put(body, "assistantId", assistant)
    _put(body, "squadId", squad)
    _put(body, "workflowId", workflow)
    if customer is not None:
        body["customer"] = _mapping(cast(Mapping[str, object], customer), "customer")
    _put(body, "firstMessage", first_message)
    _put(body, "content", content)
    _put(body, "serverUrl", server_url)
    if llm is not None:
        body["llm"] = _llm_config(llm)
    if tts is not None:
        body["tts"] = _tts_config(tts)
    if stt is not None:
        body["stt"] = _call_stt_config(stt)
    if conversation is not None:
        body["conversation"] = _mapping(conversation, "conversation")
    if background_audio is not None:
        body["backgroundAudio"] = _mapping(background_audio, "background_audio")
    if privacy is not None:
        body["privacy"] = _mapping(privacy, "privacy")
    if predefined_functions is not None:
        body["predefinedFunctions"] = _mapping(
            predefined_functions, "predefined_functions"
        )
    if tools is not None:
        body["tools"] = _tools(tools)
    if structured_output_ids is not None:
        body["structuredOutputIds"] = _strings(
            structured_output_ids, "structured_output_ids"
        )
    if file_ids is not None:
        body["fileIds"] = _strings(file_ids, "file_ids")
    if extras is not None:
        body["extras"] = _mapping(extras, "extras")
    return body


def _build_assistant_body(
    *,
    name: str,
    status: Optional[AssistantStatus],
    first_message: Optional[str],
    content: Optional[str],
    is_active: Optional[bool],
    server_url: Optional[str],
    folder_id: Optional[str],
    llm: Optional[RuntimeLlmInput],
    tts: Optional[RuntimeTtsInput],
    stt: Optional[AssistantSttConfig],
    conversation: Optional[ConversationConfig],
    background_audio: Optional[AssistantBackgroundAudio],
    privacy: Optional[PrivacyConfig],
    predefined_functions: Optional[PredefinedFunctionsConfig],
    tool_ids: Optional[Sequence[str]],
    structured_output_ids: Optional[Sequence[str]],
    knowledge_file_ids: Optional[Sequence[str]],
    use_pronunciation_library: Optional[bool],
    pronunciation_library_id: Optional[str],
    extra_fields: Mapping[str, JSONValue],
) -> RequestBody:
    body = _forward_fields(extra_fields, _ASSISTANT_FIELDS)
    body["name"] = _require_nonempty(name, "name")
    _put(body, "status", status)
    _put(body, "firstMessage", first_message)
    _put(body, "content", content)
    _put(body, "isActive", is_active)
    _put(body, "serverUrl", server_url)
    _put(body, "folderId", folder_id)
    if llm is not None:
        body["llm"] = _llm_config(llm)
    if tts is not None:
        body["tts"] = _tts_config(tts)
    if stt is not None:
        body["stt"] = _assistant_stt_config(stt)
    if conversation is not None:
        body["conversation"] = _mapping(conversation, "conversation")
    if background_audio is not None:
        body["backgroundAudio"] = _assistant_background_audio_config(
            background_audio
        )
    if privacy is not None:
        body["privacy"] = _mapping(privacy, "privacy")
    if predefined_functions is not None:
        body["predefinedFunctions"] = _mapping(
            predefined_functions, "predefined_functions"
        )
    if tool_ids is not None:
        body["toolIds"] = _strings(tool_ids, "tool_ids")
    if structured_output_ids is not None:
        body["structuredOutputIds"] = _strings(
            structured_output_ids, "structured_output_ids"
        )
    if knowledge_file_ids is not None:
        body["knowledgeFileIds"] = _strings(knowledge_file_ids, "knowledge_file_ids")
    _put(body, "usePronunciationLibrary", use_pronunciation_library)
    if pronunciation_library_id is not None:
        body["pronunciationLibraryId"] = pronunciation_library_id
    return body


def _put_update_value(body: RequestBody, key: str, value: object) -> None:
    if not isinstance(value, _NotGiven):
        body[key] = value


def _put_update_config(
    body: RequestBody,
    key: str,
    value: Union[Mapping[str, object], None, _NotGiven],
) -> None:
    if isinstance(value, _NotGiven):
        return
    body[key] = None if value is None else _mapping(value, key)


def _build_assistant_update_body(
    *,
    name: Union[str, _NotGiven],
    status: Union[AssistantStatus, _NotGiven],
    first_message: UpdateString,
    content: UpdateString,
    is_active: UpdateBool,
    server_url: UpdateString,
    folder_id: UpdateString,
    llm: UpdateLlmConfig,
    tts: UpdateTtsConfig,
    stt: UpdateSttConfig,
    conversation: UpdateConversationConfig,
    background_audio: UpdateBackgroundAudioConfig,
    privacy: UpdatePrivacyConfig,
    predefined_functions: UpdatePredefinedFunctionsConfig,
    tool_ids: UpdateStrings,
    structured_output_ids: UpdateStrings,
    knowledge_file_ids: UpdateStrings,
    use_pronunciation_library: UpdateBool,
    pronunciation_library_id: UpdateString,
    extra_fields: Mapping[str, JSONValue],
) -> RequestBody:
    body = _forward_fields(extra_fields, _ASSISTANT_FIELDS)
    if not isinstance(name, _NotGiven):
        body["name"] = _require_nonempty(name, "name")
    _put_update_value(body, "status", status)
    _put_update_value(body, "firstMessage", first_message)
    _put_update_value(body, "content", content)
    _put_update_value(body, "isActive", is_active)
    _put_update_value(body, "serverUrl", server_url)
    _put_update_value(body, "folderId", folder_id)
    if not isinstance(llm, _NotGiven):
        body["llm"] = (
            None if llm is None else _llm_config(llm)
        )
    if not isinstance(tts, _NotGiven):
        body["tts"] = None if tts is None else _tts_config(tts)
    if not isinstance(stt, _NotGiven):
        body["stt"] = None if stt is None else _assistant_stt_config(stt)
    _put_update_config(body, "conversation", conversation)
    if not isinstance(background_audio, _NotGiven):
        body["backgroundAudio"] = (
            None
            if background_audio is None
            else _assistant_background_audio_config(background_audio)
        )
    _put_update_config(body, "privacy", privacy)
    _put_update_config(body, "predefinedFunctions", predefined_functions)
    if not isinstance(tool_ids, _NotGiven):
        body["toolIds"] = _strings(tool_ids, "tool_ids")
    if not isinstance(structured_output_ids, _NotGiven):
        body["structuredOutputIds"] = _strings(
            structured_output_ids, "structured_output_ids"
        )
    if not isinstance(knowledge_file_ids, _NotGiven):
        body["knowledgeFileIds"] = _strings(
            knowledge_file_ids, "knowledge_file_ids"
        )
    _put_update_value(body, "usePronunciationLibrary", use_pronunciation_library)
    _put_update_value(body, "pronunciationLibraryId", pronunciation_library_id)
    if not body:
        raise ValueError("At least one assistant field is required for update.")
    return body


def _build_lead_body(
    *,
    name: str,
    phone: str,
    email: Optional[str],
    metadata: Optional[JSONObject],
    category_id: Optional[str],
    campaign_id: Optional[str],
    extra_fields: Mapping[str, JSONValue],
) -> RequestBody:
    body = _forward_fields(extra_fields, _LEAD_FIELDS)
    body.update(
        {
            "name": _require_nonempty(name, "name"),
            "phone": _require_nonempty(phone, "phone"),
        }
    )
    _put(body, "email", email)
    if metadata is not None:
        body["metadata"] = _mapping(metadata, "metadata")
    _put(body, "categoryId", category_id)
    _put(body, "campaignId", campaign_id)
    return body


class _AsyncLoopRunner:
    """Own one event loop so the sync facade gets cancellable async I/O."""

    def __init__(self) -> None:
        self._pid = os.getpid()
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._closed = False
        self._state_lock = threading.Lock()
        self._futures: Set[Future[object]] = set()
        self._thread = threading.Thread(
            target=_AsyncLoopRunner._serve,
            args=(self._loop, self._ready),
            daemon=True,
            name="olovoice-event-loop",
        )
        self._thread.start()
        self._ready.wait()

    @staticmethod
    def _serve(loop: asyncio.AbstractEventLoop, ready: threading.Event) -> None:
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()
        loop.close()

    def run(self, operation: Coroutine[object, object, _ResultT]) -> _ResultT:
        if os.getpid() != self._pid:
            operation.close()
            raise RuntimeError(
                "olovoice: a synchronous client cannot be reused after fork; "
                "create a new OloVoice client in the child process."
            )
        with self._state_lock:
            if self._closed:
                operation.close()
                raise RuntimeError("olovoice: client is closed.")
            future = asyncio.run_coroutine_threadsafe(operation, self._loop)
            tracked_future = cast(Future[object], future)
            self._futures.add(tracked_future)
        try:
            return future.result()
        except BaseException:
            future.cancel()
            raise
        finally:
            with self._state_lock:
                self._futures.discard(tracked_future)

    def in_creator_process(self) -> bool:
        return os.getpid() == self._pid

    def close(
        self,
        final_operation: Callable[[], Coroutine[object, object, object]],
    ) -> None:
        if os.getpid() != self._pid:
            # A Python-level fork invokes the registered pre-fork callback while
            # this runner's thread is still alive.  Do not touch an inherited
            # AsyncClient or event loop here: their transports belong to the
            # parent loop, and closing them from a new child loop can corrupt the
            # parent's keep-alive connection without reliably releasing the
            # child's duplicate descriptor.
            self._closed = True
            return
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            pending = tuple(self._futures)
        for future in pending:
            future.cancel()

        async def finish() -> None:
            await _loop_checkpoint()
            current = asyncio.current_task()
            pending_tasks = [
                task
                for task in asyncio.all_tasks()
                if task is not current and not task.done()
            ]
            if pending_tasks:
                for task in pending_tasks:
                    if task.cancelling() == 0:
                        task.cancel()
                await asyncio.gather(*pending_tasks, return_exceptions=True)
            await final_operation()
            await _loop_checkpoint()

        final_future = asyncio.run_coroutine_threadsafe(finish(), self._loop)
        try:
            final_future.result(timeout=5.0)
        finally:
            if not final_future.done():
                final_future.cancel()
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5.0)


async def _loop_checkpoint() -> None:
    loop = asyncio.get_running_loop()
    checkpoint: asyncio.Future[None] = loop.create_future()
    loop.call_soon(checkpoint.set_result, None)
    await checkpoint


class _SyncClientResources:
    """Transport state registered independently of the public client lifetime."""

    def __init__(self, runner: _AsyncLoopRunner, client: "AsyncOloVoice") -> None:
        self.runner = runner
        self.client = client
        self.invalidated = False
        self.cleanup_failed = False
        self.closing = False
        self.closed = False
        self.fork_cleanup = False
        self.cleanup_owner: Optional[int] = None

    def _raw_close(self, *, suppress_errors: bool) -> None:
        try:
            self.runner.close(self.client.close)
        except Exception:
            self.cleanup_failed = True
            if not suppress_errors:
                raise

    def close(self, *, suppress_errors: bool = False) -> None:
        if threading.current_thread() is self.runner._thread:
            if not _begin_sync_client_cleanup(self):
                return
            try:
                threading.Thread(
                    target=_finish_deferred_sync_cleanup,
                    args=(self,),
                    daemon=True,
                    name="olovoice-cleanup",
                ).start()
            except BaseException:
                self.cleanup_failed = True
                _finish_sync_client_cleanup(self)
                if not suppress_errors:
                    raise
            return
        if not _begin_sync_client_cleanup(self):
            return
        try:
            self._raw_close(suppress_errors=suppress_errors)
        finally:
            _finish_sync_client_cleanup(self)


_SYNC_CLIENTS_CONDITION = threading.Condition()
_SYNC_CLIENTS: Set[_SyncClientResources] = set()
_SYNC_CLIENTS_INITIALIZING = 0
_SYNC_CLIENTS_CLEANING = 0
_SYNC_CLIENTS_FORKING = False


def _begin_sync_client_initialization() -> None:
    global _SYNC_CLIENTS_INITIALIZING
    with _SYNC_CLIENTS_CONDITION:
        while _SYNC_CLIENTS_FORKING:
            _SYNC_CLIENTS_CONDITION.wait()
        _SYNC_CLIENTS_INITIALIZING += 1


def _finish_sync_client_initialization(
    resources: Optional[_SyncClientResources],
) -> None:
    global _SYNC_CLIENTS_INITIALIZING
    with _SYNC_CLIENTS_CONDITION:
        if resources is not None:
            _SYNC_CLIENTS.add(resources)
        _SYNC_CLIENTS_INITIALIZING -= 1
        _SYNC_CLIENTS_CONDITION.notify_all()


def _begin_sync_client_cleanup(resources: _SyncClientResources) -> bool:
    global _SYNC_CLIENTS_CLEANING
    with _SYNC_CLIENTS_CONDITION:
        while True:
            if resources.closed:
                return False
            if resources.closing:
                if (
                    resources.fork_cleanup
                    or resources.cleanup_owner == threading.get_ident()
                    or threading.current_thread() is resources.runner._thread
                ):
                    return False
                _SYNC_CLIENTS_CONDITION.wait()
                continue
            resources.closing = True
            resources.cleanup_owner = threading.get_ident()
            _SYNC_CLIENTS.discard(resources)
            _SYNC_CLIENTS_CLEANING += 1
            return True


def _finish_sync_client_cleanup(resources: _SyncClientResources) -> None:
    global _SYNC_CLIENTS_CLEANING
    with _SYNC_CLIENTS_CONDITION:
        resources.closing = False
        resources.closed = True
        resources.cleanup_owner = None
        _SYNC_CLIENTS_CLEANING -= 1
        _SYNC_CLIENTS_CONDITION.notify_all()


def _close_sync_resources(resources: _SyncClientResources) -> None:
    resources.close(suppress_errors=True)


def _finish_deferred_sync_cleanup(resources: _SyncClientResources) -> None:
    try:
        resources._raw_close(suppress_errors=True)
    finally:
        _finish_sync_client_cleanup(resources)


def _invalidate_sync_clients_before_fork() -> None:
    global _SYNC_CLIENTS_FORKING
    with _SYNC_CLIENTS_CONDITION:
        while _SYNC_CLIENTS_FORKING:
            _SYNC_CLIENTS_CONDITION.wait()
        _SYNC_CLIENTS_FORKING = True
        while _SYNC_CLIENTS_INITIALIZING or _SYNC_CLIENTS_CLEANING:
            _SYNC_CLIENTS_CONDITION.wait()
        resources_to_close = tuple(_SYNC_CLIENTS)
        _SYNC_CLIENTS.clear()
        for resources in resources_to_close:
            resources.invalidated = True
            resources.closing = True
            resources.fork_cleanup = True

    # The forking gate remains closed, but no coordination lock is held while
    # transport shutdown waits on the dedicated event-loop thread.
    for resources in resources_to_close:
        try:
            resources._raw_close(suppress_errors=True)
        finally:
            with _SYNC_CLIENTS_CONDITION:
                resources.closing = False
                resources.closed = True
                resources.fork_cleanup = False
                _SYNC_CLIENTS_CONDITION.notify_all()


def _finish_sync_clients_fork() -> None:
    global _SYNC_CLIENTS_FORKING
    with _SYNC_CLIENTS_CONDITION:
        _SYNC_CLIENTS_FORKING = False
        _SYNC_CLIENTS_CONDITION.notify_all()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=_invalidate_sync_clients_before_fork,
        after_in_parent=_finish_sync_clients_fork,
        after_in_child=_finish_sync_clients_fork,
    )


class _BaseClient:
    def __init__(self, base_url: str, timeout: float, max_retries: int) -> None:
        self._base_url = base_url
        self._timeout = timeout
        self._max_retries = max_retries

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def timeout(self) -> float:
        return self._timeout

    @property
    def max_retries(self) -> int:
        return self._max_retries

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(base_url={self.base_url!r}, "
            f"timeout={self.timeout!r}, max_retries={self.max_retries!r})"
        )


class OloVoice(_BaseClient):
    """Synchronous olovoice Public API client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        default_headers: Optional[Mapping[str, str]] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        dangerously_allow_custom_base_url: bool = False,
        dangerously_allow_insecure_http: bool = False,
    ) -> None:
        if transport is not None and not isinstance(
            transport, httpx.AsyncBaseTransport
        ):
            raise TypeError(
                "transport must implement httpx.AsyncBaseTransport; "
                "httpx.MockTransport supports both sync and async clients."
            )
        normalized_timeout, normalized_retries = _validate_options(timeout, max_retries)
        normalized_base_url = _validate_base_url(
            base_url,
            dangerously_allow_custom_base_url=dangerously_allow_custom_base_url,
            dangerously_allow_insecure_http=dangerously_allow_insecure_http,
        )
        super().__init__(normalized_base_url, normalized_timeout, normalized_retries)
        _begin_sync_client_initialization()
        registered_resources: Optional[_SyncClientResources] = None
        try:
            self._async_client = AsyncOloVoice(
                api_key=api_key,
                base_url=normalized_base_url,
                timeout=normalized_timeout,
                max_retries=normalized_retries,
                default_headers=default_headers,
                transport=transport,
                dangerously_allow_custom_base_url=dangerously_allow_custom_base_url,
                dangerously_allow_insecure_http=dangerously_allow_insecure_http,
            )
            self._runner = _AsyncLoopRunner()
            self._resources = _SyncClientResources(
                self._runner,
                self._async_client,
            )
            self._finalizer = weakref.finalize(
                self,
                _close_sync_resources,
                self._resources,
            )
            setattr(self._finalizer, "atexit", False)
            registered_resources = self._resources
        finally:
            _finish_sync_client_initialization(registered_resources)

    def close(self) -> None:
        try:
            self._resources.close()
        finally:
            self._finalizer.detach()

    def __enter__(self) -> "OloVoice":
        return self

    def __exit__(self, exc_type: object, exc_value: object, traceback: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Query] = None,
        body: Optional[RequestBody] = None,
    ) -> JSONObject:
        if self._resources.invalidated:
            detail = (
                " Cleanup failed before fork."
                if self._resources.cleanup_failed
                else ""
            )
            raise RuntimeError(
                "olovoice: fork invalidated this synchronous client in both "
                "parent and child; create a new OloVoice client after fork."
                + detail
            )
        if not self._runner.in_creator_process():
            raise RuntimeError(
                "olovoice: a synchronous client cannot be reused after fork; "
                "create a new OloVoice client in the child process."
            )
        return self._runner.run(
            self._async_client._request(method, path, query=query, body=body)
        )

    def create_call(
        self,
        *,
        phone_number_id: str,
        customer: Customer,
        llm: RuntimeLlmInput,
        conversation: ConversationConfig,
        background_audio: CallBackgroundAudio,
        assistant_id: Optional[str] = None,
        squad_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        first_message: Optional[str] = None,
        content: Optional[str] = None,
        server_url: Optional[str] = None,
        tts: Optional[RuntimeTtsInput] = None,
        stt: Optional[CallSttConfig] = None,
        privacy: Optional[PrivacyConfig] = None,
        predefined_functions: Optional[PredefinedFunctionsConfig] = None,
        tools: Optional[Sequence[InlineTool]] = None,
        tool_ids: Optional[Sequence[str]] = None,
        structured_output_ids: Optional[Sequence[str]] = None,
        file_ids: Optional[Sequence[str]] = None,
        extras: Optional[JSONObject] = None,
        pronunciation_library_id: Optional[str] = None,
        **extra_fields: JSONValue,
    ) -> CreateCallResponse:
        body = _build_call_body(
            phone_number_id=phone_number_id,
            customer=customer,
            llm=llm,
            conversation=conversation,
            background_audio=background_audio,
            assistant_id=assistant_id,
            squad_id=squad_id,
            workflow_id=workflow_id,
            first_message=first_message,
            content=content,
            server_url=server_url,
            tts=tts,
            stt=stt,
            privacy=privacy,
            predefined_functions=predefined_functions,
            tools=tools,
            tool_ids=tool_ids,
            structured_output_ids=structured_output_ids,
            file_ids=file_ids,
            extras=extras,
            pronunciation_library_id=pronunciation_library_id,
            extra_fields=extra_fields,
        )
        return cast(CreateCallResponse, self._request("POST", "/call", body=body))

    def create_web_call(
        self,
        *,
        organization_id: str,
        assistant_id: Optional[str] = None,
        squad_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        customer: Optional[WebCustomer] = None,
        first_message: Optional[str] = None,
        content: Optional[str] = None,
        server_url: Optional[str] = None,
        llm: Optional[RuntimeLlmInput] = None,
        tts: Optional[RuntimeTtsInput] = None,
        stt: Optional[CallSttConfig] = None,
        conversation: Optional[ConversationConfig] = None,
        background_audio: Optional[CallBackgroundAudio] = None,
        privacy: Optional[PrivacyConfig] = None,
        predefined_functions: Optional[PredefinedFunctionsConfig] = None,
        tools: Optional[Sequence[InlineTool]] = None,
        structured_output_ids: Optional[Sequence[str]] = None,
        file_ids: Optional[Sequence[str]] = None,
        extras: Optional[JSONObject] = None,
        **extra_fields: JSONValue,
    ) -> CreateWebCallResponse:
        body = _build_web_call_body(
            organization_id=organization_id,
            assistant_id=assistant_id,
            squad_id=squad_id,
            workflow_id=workflow_id,
            customer=customer,
            first_message=first_message,
            content=content,
            server_url=server_url,
            llm=llm,
            tts=tts,
            stt=stt,
            conversation=conversation,
            background_audio=background_audio,
            privacy=privacy,
            predefined_functions=predefined_functions,
            tools=tools,
            structured_output_ids=structured_output_ids,
            file_ids=file_ids,
            extras=extras,
            extra_fields=extra_fields,
        )
        return cast(
            CreateWebCallResponse, self._request("POST", "/web-call", body=body)
        )

    def list_call_logs(
        self,
        *,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        organization_id: Optional[str] = None,
    ) -> ListCallLogsResponse:
        return cast(
            ListCallLogsResponse,
            self._request(
                "GET",
                "/call-logs",
                query={"limit": limit, "page": page, "organizationId": organization_id},
            ),
        )

    def get_call_log(
        self, call_id: str, *, organization_id: Optional[str] = None
    ) -> GetCallLogResponse:
        call = _require_nonempty(call_id, "call_id")
        return cast(
            GetCallLogResponse,
            self._request(
                "GET",
                f"/call-logs/{quote(call, safe='')}",
                query={"organizationId": organization_id},
            ),
        )

    def refresh_recording_url(
        self, call_id: str, *, organization_id: Optional[str] = None
    ) -> RecordingUrlResponse:
        call = _require_nonempty(call_id, "call_id")
        return cast(
            RecordingUrlResponse,
            self._request(
                "GET",
                f"/call-logs/{quote(call, safe='')}/recording-url",
                query={"organizationId": organization_id},
            ),
        )

    def list_assistants(self, *, limit: Optional[int] = None) -> ListAssistantsResponse:
        return cast(
            ListAssistantsResponse,
            self._request("GET", "/assistants", query={"limit": limit}),
        )

    def create_assistant(
        self,
        *,
        name: str,
        status: Optional[AssistantStatus] = None,
        first_message: Optional[str] = None,
        content: Optional[str] = None,
        is_active: Optional[bool] = None,
        server_url: Optional[str] = None,
        folder_id: Optional[str] = None,
        llm: Optional[RuntimeLlmInput] = None,
        tts: Optional[RuntimeTtsInput] = None,
        stt: Optional[AssistantSttConfig] = None,
        conversation: Optional[ConversationConfig] = None,
        background_audio: Optional[AssistantBackgroundAudio] = None,
        privacy: Optional[PrivacyConfig] = None,
        predefined_functions: Optional[PredefinedFunctionsConfig] = None,
        tool_ids: Optional[Sequence[str]] = None,
        structured_output_ids: Optional[Sequence[str]] = None,
        knowledge_file_ids: Optional[Sequence[str]] = None,
        use_pronunciation_library: Optional[bool] = None,
        pronunciation_library_id: Optional[str] = None,
        **extra_fields: JSONValue,
    ) -> CreateAssistantResponse:
        body = _build_assistant_body(
            name=name,
            status=status,
            first_message=first_message,
            content=content,
            is_active=is_active,
            server_url=server_url,
            folder_id=folder_id,
            llm=llm,
            tts=tts,
            stt=stt,
            conversation=conversation,
            background_audio=background_audio,
            privacy=privacy,
            predefined_functions=predefined_functions,
            tool_ids=tool_ids,
            structured_output_ids=structured_output_ids,
            knowledge_file_ids=knowledge_file_ids,
            use_pronunciation_library=use_pronunciation_library,
            pronunciation_library_id=pronunciation_library_id,
            extra_fields=extra_fields,
        )
        return cast(
            CreateAssistantResponse, self._request("POST", "/assistants", body=body)
        )

    def get_assistant(self, assistant_id: str) -> AssistantObjectResponse:
        assistant = _require_nonempty(assistant_id, "assistant_id")
        return cast(
            AssistantObjectResponse,
            self._request("GET", f"/assistants/{quote(assistant, safe='')}"),
        )

    def update_assistant(
        self,
        assistant_id: str,
        *,
        name: Union[str, _NotGiven] = _NOT_GIVEN,
        status: Union[AssistantStatus, _NotGiven] = _NOT_GIVEN,
        first_message: UpdateString = _NOT_GIVEN,
        content: UpdateString = _NOT_GIVEN,
        is_active: UpdateBool = _NOT_GIVEN,
        server_url: UpdateString = _NOT_GIVEN,
        folder_id: UpdateString = _NOT_GIVEN,
        llm: UpdateLlmConfig = _NOT_GIVEN,
        tts: UpdateTtsConfig = _NOT_GIVEN,
        stt: UpdateSttConfig = _NOT_GIVEN,
        conversation: UpdateConversationConfig = _NOT_GIVEN,
        background_audio: UpdateBackgroundAudioConfig = _NOT_GIVEN,
        privacy: UpdatePrivacyConfig = _NOT_GIVEN,
        predefined_functions: UpdatePredefinedFunctionsConfig = _NOT_GIVEN,
        tool_ids: UpdateStrings = _NOT_GIVEN,
        structured_output_ids: UpdateStrings = _NOT_GIVEN,
        knowledge_file_ids: UpdateStrings = _NOT_GIVEN,
        use_pronunciation_library: UpdateBool = _NOT_GIVEN,
        pronunciation_library_id: UpdateString = _NOT_GIVEN,
        **extra_fields: JSONValue,
    ) -> UpdateAssistantResponse:
        assistant = _require_nonempty(assistant_id, "assistant_id")
        body = _build_assistant_update_body(
            name=name,
            status=status,
            first_message=first_message,
            content=content,
            is_active=is_active,
            server_url=server_url,
            folder_id=folder_id,
            llm=llm,
            tts=tts,
            stt=stt,
            conversation=conversation,
            background_audio=background_audio,
            privacy=privacy,
            predefined_functions=predefined_functions,
            tool_ids=tool_ids,
            structured_output_ids=structured_output_ids,
            knowledge_file_ids=knowledge_file_ids,
            use_pronunciation_library=use_pronunciation_library,
            pronunciation_library_id=pronunciation_library_id,
            extra_fields=extra_fields,
        )
        return cast(
            UpdateAssistantResponse,
            self._request(
                "PATCH", f"/assistants/{quote(assistant, safe='')}", body=body
            ),
        )

    def delete_assistant(self, assistant_id: str) -> DeleteAssistantResponse:
        assistant = _require_nonempty(assistant_id, "assistant_id")
        return cast(
            DeleteAssistantResponse,
            self._request("DELETE", f"/assistants/{quote(assistant, safe='')}"),
        )

    def create_lead(
        self,
        *,
        name: str,
        phone: str,
        email: Optional[str] = None,
        metadata: Optional[JSONObject] = None,
        category_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        **extra_fields: JSONValue,
    ) -> CreateLeadResponse:
        body = _build_lead_body(
            name=name,
            phone=phone,
            email=email,
            metadata=metadata,
            category_id=category_id,
            campaign_id=campaign_id,
            extra_fields=extra_fields,
        )
        return cast(CreateLeadResponse, self._request("POST", "/leads", body=body))

    def get_metrics(
        self,
        *,
        range: Optional[MetricsRange] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        assistant_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> MetricsResponse:
        return cast(
            MetricsResponse,
            self._request(
                "GET",
                "/metrics",
                query={
                    "range": range,
                    "startDate": start_date,
                    "endDate": end_date,
                    "assistantId": assistant_id,
                    "organizationId": organization_id,
                },
            ),
        )


class AsyncOloVoice(_BaseClient):
    """Asynchronous client with the same method surface as :class:`OloVoice`."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = _DEFAULT_TIMEOUT,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        default_headers: Optional[Mapping[str, str]] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        dangerously_allow_custom_base_url: bool = False,
        dangerously_allow_insecure_http: bool = False,
    ) -> None:
        if transport is not None and not isinstance(
            transport, httpx.AsyncBaseTransport
        ):
            raise TypeError(
                "transport must implement httpx.AsyncBaseTransport; "
                "httpx.MockTransport supports both sync and async clients."
            )
        normalized_timeout, normalized_retries = _validate_options(timeout, max_retries)
        normalized_base_url = _validate_base_url(
            base_url,
            dangerously_allow_custom_base_url=dangerously_allow_custom_base_url,
            dangerously_allow_insecure_http=dangerously_allow_insecure_http,
        )
        headers = _build_headers(_resolve_api_key(api_key), default_headers)
        super().__init__(normalized_base_url, normalized_timeout, normalized_retries)
        self._http = httpx.AsyncClient(
            base_url=normalized_base_url,
            headers=headers,
            timeout=normalized_timeout,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "AsyncOloVoice":
        return self

    async def __aexit__(
        self, exc_type: object, exc_value: object, traceback: object
    ) -> None:
        await self.close()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Query] = None,
        body: Optional[RequestBody] = None,
    ) -> JSONObject:
        attempts = self.max_retries + 1 if method == "GET" else 1
        last_error: Optional[OloVoiceError] = None
        delay = 0.0
        for attempt in range(attempts):
            if attempt:
                await asyncio.sleep(delay)
            deadline = time.monotonic() + self.timeout
            streamed_response: Optional[httpx.Response] = None
            attempt_protocol_error: Optional[InvalidResponseError] = None

            async def perform_attempt(request_timeout: float) -> httpx.Response:
                nonlocal attempt_protocol_error, streamed_response
                async with self._http.stream(
                    method,
                    path,
                    params=_clean_query(query or {}),
                    json=body,
                    timeout=request_timeout,
                ) as response_stream:
                    streamed_response = response_stream
                    try:
                        return await _buffer_async_response(
                            response_stream, deadline, self.timeout
                        )
                    except InvalidResponseError as exc:
                        attempt_protocol_error = exc
                        raise

            try:
                remaining = _remaining_or_raise(deadline, self.timeout)
                response = await asyncio.wait_for(
                    perform_attempt(remaining), timeout=remaining
                )
            except asyncio.TimeoutError as exc:
                if attempt_protocol_error is not None:
                    last_error, retryable = _classify_protocol_error(
                        attempt_protocol_error, streamed_response
                    )
                    if not retryable:
                        raise last_error from None
                    delay = _retry_delay_for_error(last_error, attempt + 1)
                    continue
                connection_error = _deadline_error(self.timeout, streamed_response)
                connection_error.__cause__ = exc
                last_error, retryable = _classify_transport_error(
                    connection_error, streamed_response
                )
                if not retryable:
                    raise last_error from exc
                delay = _retry_delay_for_error(last_error, attempt + 1)
                continue
            except InvalidResponseError as exc:
                last_error, retryable = _classify_protocol_error(
                    exc, streamed_response
                )
                if not retryable:
                    if last_error is exc:
                        raise
                    raise last_error from exc
                delay = _retry_delay_for_error(last_error, attempt + 1)
                continue
            except APIConnectionError as exc:
                last_error, retryable = _classify_transport_error(
                    exc, streamed_response
                )
                if not retryable:
                    raise last_error from exc
                delay = _retry_delay_for_error(last_error, attempt + 1)
                continue
            except httpx.HTTPError as exc:
                if time.monotonic() >= deadline:
                    connection_error = _deadline_error(
                        self.timeout, streamed_response
                    )
                else:
                    detail = (
                        f"Request timed out after {self.timeout:g}s"
                        if isinstance(exc, httpx.TimeoutException)
                        else f"Request failed: {exc}"
                    )
                    connection_error = APIConnectionError(
                        detail,
                        status=(
                            streamed_response.status_code
                            if streamed_response is not None
                            else None
                        ),
                        request_id=(
                            _request_id(streamed_response)
                            if streamed_response is not None
                            else None
                        ),
                        retry_after=(
                            _retry_after_seconds(streamed_response)
                            if streamed_response is not None
                            else None
                        ),
                    )
                connection_error.__cause__ = exc
                last_error, retryable = _classify_transport_error(
                    connection_error, streamed_response
                )
                if not retryable:
                    raise last_error from exc
                delay = _retry_delay_for_error(last_error, attempt + 1)
                continue
            try:
                if response.is_success:
                    return _success_object(response, deadline, self.timeout)
                last_error = _error_for_response(response, deadline, self.timeout)
            except APIConnectionError as exc:
                last_error, retryable = _classify_transport_error(exc, response)
                if not retryable:
                    raise last_error from exc
                delay = _retry_delay_for_error(last_error, attempt + 1)
                continue
            if response.status_code != 429 and response.status_code < 500:
                raise last_error
            delay = _retry_delay(response, attempt + 1)
        if last_error is None:
            raise RuntimeError("olovoice: request loop ended without a response or error.")
        raise last_error

    async def create_call(
        self,
        *,
        phone_number_id: str,
        customer: Customer,
        llm: RuntimeLlmInput,
        conversation: ConversationConfig,
        background_audio: CallBackgroundAudio,
        assistant_id: Optional[str] = None,
        squad_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        first_message: Optional[str] = None,
        content: Optional[str] = None,
        server_url: Optional[str] = None,
        tts: Optional[RuntimeTtsInput] = None,
        stt: Optional[CallSttConfig] = None,
        privacy: Optional[PrivacyConfig] = None,
        predefined_functions: Optional[PredefinedFunctionsConfig] = None,
        tools: Optional[Sequence[InlineTool]] = None,
        tool_ids: Optional[Sequence[str]] = None,
        structured_output_ids: Optional[Sequence[str]] = None,
        file_ids: Optional[Sequence[str]] = None,
        extras: Optional[JSONObject] = None,
        pronunciation_library_id: Optional[str] = None,
        **extra_fields: JSONValue,
    ) -> CreateCallResponse:
        body = _build_call_body(
            phone_number_id=phone_number_id,
            customer=customer,
            llm=llm,
            conversation=conversation,
            background_audio=background_audio,
            assistant_id=assistant_id,
            squad_id=squad_id,
            workflow_id=workflow_id,
            first_message=first_message,
            content=content,
            server_url=server_url,
            tts=tts,
            stt=stt,
            privacy=privacy,
            predefined_functions=predefined_functions,
            tools=tools,
            tool_ids=tool_ids,
            structured_output_ids=structured_output_ids,
            file_ids=file_ids,
            extras=extras,
            pronunciation_library_id=pronunciation_library_id,
            extra_fields=extra_fields,
        )
        return cast(CreateCallResponse, await self._request("POST", "/call", body=body))

    async def create_web_call(
        self,
        *,
        organization_id: str,
        assistant_id: Optional[str] = None,
        squad_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        customer: Optional[WebCustomer] = None,
        first_message: Optional[str] = None,
        content: Optional[str] = None,
        server_url: Optional[str] = None,
        llm: Optional[RuntimeLlmInput] = None,
        tts: Optional[RuntimeTtsInput] = None,
        stt: Optional[CallSttConfig] = None,
        conversation: Optional[ConversationConfig] = None,
        background_audio: Optional[CallBackgroundAudio] = None,
        privacy: Optional[PrivacyConfig] = None,
        predefined_functions: Optional[PredefinedFunctionsConfig] = None,
        tools: Optional[Sequence[InlineTool]] = None,
        structured_output_ids: Optional[Sequence[str]] = None,
        file_ids: Optional[Sequence[str]] = None,
        extras: Optional[JSONObject] = None,
        **extra_fields: JSONValue,
    ) -> CreateWebCallResponse:
        body = _build_web_call_body(
            organization_id=organization_id,
            assistant_id=assistant_id,
            squad_id=squad_id,
            workflow_id=workflow_id,
            customer=customer,
            first_message=first_message,
            content=content,
            server_url=server_url,
            llm=llm,
            tts=tts,
            stt=stt,
            conversation=conversation,
            background_audio=background_audio,
            privacy=privacy,
            predefined_functions=predefined_functions,
            tools=tools,
            structured_output_ids=structured_output_ids,
            file_ids=file_ids,
            extras=extras,
            extra_fields=extra_fields,
        )
        return cast(
            CreateWebCallResponse,
            await self._request("POST", "/web-call", body=body),
        )

    async def list_call_logs(
        self,
        *,
        limit: Optional[int] = None,
        page: Optional[int] = None,
        organization_id: Optional[str] = None,
    ) -> ListCallLogsResponse:
        return cast(
            ListCallLogsResponse,
            await self._request(
                "GET",
                "/call-logs",
                query={"limit": limit, "page": page, "organizationId": organization_id},
            ),
        )

    async def get_call_log(
        self, call_id: str, *, organization_id: Optional[str] = None
    ) -> GetCallLogResponse:
        call = _require_nonempty(call_id, "call_id")
        return cast(
            GetCallLogResponse,
            await self._request(
                "GET",
                f"/call-logs/{quote(call, safe='')}",
                query={"organizationId": organization_id},
            ),
        )

    async def refresh_recording_url(
        self, call_id: str, *, organization_id: Optional[str] = None
    ) -> RecordingUrlResponse:
        call = _require_nonempty(call_id, "call_id")
        return cast(
            RecordingUrlResponse,
            await self._request(
                "GET",
                f"/call-logs/{quote(call, safe='')}/recording-url",
                query={"organizationId": organization_id},
            ),
        )

    async def list_assistants(
        self, *, limit: Optional[int] = None
    ) -> ListAssistantsResponse:
        return cast(
            ListAssistantsResponse,
            await self._request("GET", "/assistants", query={"limit": limit}),
        )

    async def create_assistant(
        self,
        *,
        name: str,
        status: Optional[AssistantStatus] = None,
        first_message: Optional[str] = None,
        content: Optional[str] = None,
        is_active: Optional[bool] = None,
        server_url: Optional[str] = None,
        folder_id: Optional[str] = None,
        llm: Optional[RuntimeLlmInput] = None,
        tts: Optional[RuntimeTtsInput] = None,
        stt: Optional[AssistantSttConfig] = None,
        conversation: Optional[ConversationConfig] = None,
        background_audio: Optional[AssistantBackgroundAudio] = None,
        privacy: Optional[PrivacyConfig] = None,
        predefined_functions: Optional[PredefinedFunctionsConfig] = None,
        tool_ids: Optional[Sequence[str]] = None,
        structured_output_ids: Optional[Sequence[str]] = None,
        knowledge_file_ids: Optional[Sequence[str]] = None,
        use_pronunciation_library: Optional[bool] = None,
        pronunciation_library_id: Optional[str] = None,
        **extra_fields: JSONValue,
    ) -> CreateAssistantResponse:
        body = _build_assistant_body(
            name=name,
            status=status,
            first_message=first_message,
            content=content,
            is_active=is_active,
            server_url=server_url,
            folder_id=folder_id,
            llm=llm,
            tts=tts,
            stt=stt,
            conversation=conversation,
            background_audio=background_audio,
            privacy=privacy,
            predefined_functions=predefined_functions,
            tool_ids=tool_ids,
            structured_output_ids=structured_output_ids,
            knowledge_file_ids=knowledge_file_ids,
            use_pronunciation_library=use_pronunciation_library,
            pronunciation_library_id=pronunciation_library_id,
            extra_fields=extra_fields,
        )
        return cast(
            CreateAssistantResponse,
            await self._request("POST", "/assistants", body=body),
        )

    async def get_assistant(self, assistant_id: str) -> AssistantObjectResponse:
        assistant = _require_nonempty(assistant_id, "assistant_id")
        return cast(
            AssistantObjectResponse,
            await self._request("GET", f"/assistants/{quote(assistant, safe='')}"),
        )

    async def update_assistant(
        self,
        assistant_id: str,
        *,
        name: Union[str, _NotGiven] = _NOT_GIVEN,
        status: Union[AssistantStatus, _NotGiven] = _NOT_GIVEN,
        first_message: UpdateString = _NOT_GIVEN,
        content: UpdateString = _NOT_GIVEN,
        is_active: UpdateBool = _NOT_GIVEN,
        server_url: UpdateString = _NOT_GIVEN,
        folder_id: UpdateString = _NOT_GIVEN,
        llm: UpdateLlmConfig = _NOT_GIVEN,
        tts: UpdateTtsConfig = _NOT_GIVEN,
        stt: UpdateSttConfig = _NOT_GIVEN,
        conversation: UpdateConversationConfig = _NOT_GIVEN,
        background_audio: UpdateBackgroundAudioConfig = _NOT_GIVEN,
        privacy: UpdatePrivacyConfig = _NOT_GIVEN,
        predefined_functions: UpdatePredefinedFunctionsConfig = _NOT_GIVEN,
        tool_ids: UpdateStrings = _NOT_GIVEN,
        structured_output_ids: UpdateStrings = _NOT_GIVEN,
        knowledge_file_ids: UpdateStrings = _NOT_GIVEN,
        use_pronunciation_library: UpdateBool = _NOT_GIVEN,
        pronunciation_library_id: UpdateString = _NOT_GIVEN,
        **extra_fields: JSONValue,
    ) -> UpdateAssistantResponse:
        assistant = _require_nonempty(assistant_id, "assistant_id")
        body = _build_assistant_update_body(
            name=name,
            status=status,
            first_message=first_message,
            content=content,
            is_active=is_active,
            server_url=server_url,
            folder_id=folder_id,
            llm=llm,
            tts=tts,
            stt=stt,
            conversation=conversation,
            background_audio=background_audio,
            privacy=privacy,
            predefined_functions=predefined_functions,
            tool_ids=tool_ids,
            structured_output_ids=structured_output_ids,
            knowledge_file_ids=knowledge_file_ids,
            use_pronunciation_library=use_pronunciation_library,
            pronunciation_library_id=pronunciation_library_id,
            extra_fields=extra_fields,
        )
        return cast(
            UpdateAssistantResponse,
            await self._request(
                "PATCH", f"/assistants/{quote(assistant, safe='')}", body=body
            ),
        )

    async def delete_assistant(self, assistant_id: str) -> DeleteAssistantResponse:
        assistant = _require_nonempty(assistant_id, "assistant_id")
        return cast(
            DeleteAssistantResponse,
            await self._request("DELETE", f"/assistants/{quote(assistant, safe='')}"),
        )

    async def create_lead(
        self,
        *,
        name: str,
        phone: str,
        email: Optional[str] = None,
        metadata: Optional[JSONObject] = None,
        category_id: Optional[str] = None,
        campaign_id: Optional[str] = None,
        **extra_fields: JSONValue,
    ) -> CreateLeadResponse:
        body = _build_lead_body(
            name=name,
            phone=phone,
            email=email,
            metadata=metadata,
            category_id=category_id,
            campaign_id=campaign_id,
            extra_fields=extra_fields,
        )
        return cast(
            CreateLeadResponse, await self._request("POST", "/leads", body=body)
        )

    async def get_metrics(
        self,
        *,
        range: Optional[MetricsRange] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        assistant_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> MetricsResponse:
        return cast(
            MetricsResponse,
            await self._request(
                "GET",
                "/metrics",
                query={
                    "range": range,
                    "startDate": start_date,
                    "endDate": end_date,
                    "assistantId": assistant_id,
                    "organizationId": organization_id,
                },
            ),
        )
