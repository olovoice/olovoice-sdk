from __future__ import annotations

import asyncio
import gc
import gzip
import inspect
import json
import os
import shutil
import socket
import socketserver
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import (
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    FrozenSet,
    Generator,
    Iterator,
    List,
    Mapping,
    Optional,
    Tuple,
    Type,
    Union,
    cast,
)
from urllib.parse import quote

import httpx
import pytest
import olovoice._client as client_module

from olovoice import (
    APIConnectionError,
    AssistantBackgroundAudio,
    AssistantSttConfig,
    AsyncOloVoice,
    AuthenticationError,
    BadRequestError,
    CallLog,
    CallSttConfig,
    InternalServerError,
    InvalidResponseError,
    LatencyBreakdown,
    MetricsResponse,
    OloVoice,
    OloVoiceError,
    PaymentRequiredError,
    RateLimitError,
    RuntimeLlmInput,
    RuntimeTtsInput,
)


Handler = Callable[[httpx.Request], httpx.Response]
AsyncHandler = Callable[[httpx.Request], Awaitable[httpx.Response]]


def make_client(
    handler: Union[Handler, AsyncHandler],
    *,
    max_retries: int = 2,
    default_headers: Optional[Mapping[str, str]] = None,
    timeout: float = 30.0,
    base_url: str = "https://api.olovoice.ai",
    dangerously_allow_custom_base_url: bool = False,
    dangerously_allow_insecure_http: bool = False,
) -> OloVoice:
    async def dispatch(request: httpx.Request) -> httpx.Response:
        result = handler(request)
        if inspect.isawaitable(result):
            return await result
        return result

    return OloVoice(
        api_key="sk-test",
        max_retries=max_retries,
        default_headers=default_headers,
        timeout=timeout,
        base_url=base_url,
        dangerously_allow_custom_base_url=dangerously_allow_custom_base_url,
        dangerously_allow_insecure_http=dangerously_allow_insecure_http,
        transport=httpx.MockTransport(dispatch),
    )


def make_async_client(
    handler: Union[Handler, AsyncHandler],
    *,
    max_retries: int = 2,
    timeout: float = 30.0,
) -> AsyncOloVoice:
    async def dispatch(request: httpx.Request) -> httpx.Response:
        result = handler(request)
        if inspect.isawaitable(result):
            return await result
        return result

    return AsyncOloVoice(
        api_key="sk-test",
        max_retries=max_retries,
        timeout=timeout,
        transport=httpx.MockTransport(dispatch),
    )


def request_json(request: httpx.Request) -> Dict[str, object]:
    value = cast(object, json.loads(request.content.decode("utf-8")))
    if not isinstance(value, dict):
        raise AssertionError("request body was not an object")
    return cast(Dict[str, object], value)


def call_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "success": True,
            "subscriptionLimits": {
                "concurrencyBlocked": False,
                "concurrencyLimit": 10,
                "remainingConcurrentCalls": 9,
            },
            "payload": {
                "callId": "c-1",
                "phoneNumberId": "p-1",
                "customer": {"number": "+905551234567"},
                "organizationId": "o-1",
                "requestId": "r-1",
            },
            "carrier": {"ok": True},
        },
    )


def test_sends_bearer_auth_and_camelcase_body() -> None:
    seen: List[Tuple[str, str, Dict[str, object]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (str(request.url), request.headers["authorization"], request_json(request))
        )
        return call_response()

    client = make_client(handler)
    response = client.create_call(
        assistant_id="a-1",
        phone_number_id="p-1",
        customer={"number": "+905551234567"},
        first_message="Merhaba",
        content="Yardimci ol",
        llm={"provider": "openai", "model": "gpt-4o-mini"},
        tts={"provider": "elevenlabs", "model": "eleven_turbo_v2_5", "voiceId": "v-1"},
        stt={"provider": "deepgram", "model": "nova-3"},
        conversation={},
        background_audio={},
    )
    assert response["payload"]["callId"] == "c-1"
    url, auth, body = seen[0]
    assert url == "https://api.olovoice.ai/call"
    assert auth == "Bearer sk-test"
    assert body["phoneNumberId"] == "p-1"
    assert body["assistantId"] == "a-1"
    llm = cast(Dict[str, object], body["llm"])
    assert llm["model"] == "gpt-4o-mini"
    assert "phone_number_id" not in body


def test_query_params_and_path_encoding() -> None:
    seen: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    client = make_client(handler)
    client.list_call_logs(limit=50, page=2)
    assert str(seen[-1].url) == "https://api.olovoice.ai/call-logs?limit=50&page=2"
    client.get_call_log("id with space")
    assert "/call-logs/id%20with%20space" in str(seen[-1].url)


ERROR_CASES: List[Tuple[int, Dict[str, object], Type[OloVoiceError]]] = [
    (401, {"error": "Unauthorized"}, AuthenticationError),
    (400, {"success": False, "error": "customer.number gecersiz"}, BadRequestError),
    (402, {"success": False, "error": "Yetersiz bakiye"}, PaymentRequiredError),
]


@pytest.mark.parametrize("status,body,error_type", ERROR_CASES)
def test_error_mapping(
    status: int, body: Dict[str, object], error_type: Type[OloVoiceError]
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    client = make_client(handler)
    with pytest.raises(error_type) as info:
        client.create_lead(name="a", phone="1")
    expected = body["error"]
    assert isinstance(expected, str)
    assert info.value.status == status
    assert str(info.value) == expected


def test_get_retries_on_429_post_does_not(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: List[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record_sleep)
    count = 0

    def flaky(_request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if count < 2:
            return httpx.Response(429, json={"error": "rate limited"})
        return httpx.Response(200, json={"success": True, "assistants": []})

    client = make_client(flaky, max_retries=2)
    assert client.list_assistants()["success"] is True
    assert count == 2
    assert sleeps == [0.5]

    count = 0

    def count_and_429(_request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        return httpx.Response(429, json={"error": "rate limited"})

    post_client = make_client(count_and_429, max_retries=5)
    with pytest.raises(RateLimitError):
        post_client.create_lead(name="a", phone="1")
    assert count == 1


def test_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLOVOICE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="missing API key"):
        OloVoice()


def test_async_client_roundtrip() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer sk-test"
        return httpx.Response(
            200,
            json={
                "success": True,
                "callId": "web-1",
                "roomName": "room-1",
                "token": "t",
                "connectionUrl": "wss://rtc.example",
                "expiresInSeconds": 600,
                "startedAt": "2026-08-10T00:00:00Z",
                "subscriptionLimits": {
                    "concurrencyBlocked": False,
                    "concurrencyLimit": 10,
                    "remainingConcurrentCalls": 9,
                },
            },
        )

    async def run() -> str:
        async with AsyncOloVoice(
            api_key="sk-test", transport=httpx.MockTransport(handler)
        ) as client:
            response = await client.create_web_call(
                organization_id="o-1", assistant_id="a-1"
            )
            return response["callId"]

    assert asyncio.run(run()) == "web-1"


def object_handler(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={})


def valid_llm() -> RuntimeLlmInput:
    return {"provider": "openai", "model": "gpt-4o-mini"}


def valid_tts() -> RuntimeTtsInput:
    return {
        "provider": "elevenlabs",
        "model": "eleven_turbo_v2_5",
        "voiceId": "voice-1",
    }


def place_squad_call(
    client: OloVoice,
    *,
    llm: RuntimeLlmInput,
    tts: Optional[RuntimeTtsInput],
    stt: Optional[CallSttConfig],
) -> None:
    client.create_call(
        squad_id="squad-1",
        phone_number_id="phone-1",
        customer={"number": "+905551234567"},
        llm=llm,
        tts=tts,
        stt=stt,
        conversation={},
        background_audio={},
    )


def test_direct_call_requires_prompt_and_selector() -> None:
    client = make_client(object_handler)
    with pytest.raises(ValueError, match="assistant_id"):
        client.create_call(
            phone_number_id="phone-1",
            customer={"number": "+905551234567"},
            llm=valid_llm(),
            tts=valid_tts(),
            stt={"provider": "deepgram"},
            conversation={},
            background_audio={},
        )

    with pytest.raises(ValueError, match="first_message"):
        client.create_call(
            assistant_id="assistant-1",
            phone_number_id="phone-1",
            customer={"number": "+905551234567"},
            llm=valid_llm(),
            tts=valid_tts(),
            stt={"provider": "deepgram"},
            conversation={},
            background_audio={},
        )


def test_classic_and_realtime_audio_requirements() -> None:
    client = make_client(object_handler)
    with pytest.raises(ValueError, match="tts is required"):
        place_squad_call(
            client,
            llm=valid_llm(),
            tts=None,
            stt={"provider": "deepgram"},
        )
    with pytest.raises(ValueError, match="stt is required"):
        place_squad_call(client, llm=valid_llm(), tts=valid_tts(), stt=None)

    half_cascade: RuntimeLlmInput = {
        "provider": "openai-realtime",
        "model": "gpt-realtime",
        "realtimeMode": "halfCascade",
    }
    place_squad_call(client, llm=half_cascade, tts=valid_tts(), stt=None)

    native_audio: RuntimeLlmInput = {
        "provider": "openai",
        "model": "gpt-realtime-1.5",
        "realtimeMode": "nativeAudio",
    }
    place_squad_call(client, llm=native_audio, tts=None, stt=None)


def test_realtime_mode_does_not_activate_an_unsupported_model() -> None:
    client = make_client(object_handler)
    non_realtime = cast(
        RuntimeLlmInput,
        {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "realtimeMode": "nativeAudio",
        },
    )
    with pytest.raises(ValueError, match="tts is required"):
        place_squad_call(client, llm=non_realtime, tts=None, stt=None)


INVALID_PROVIDER_CASES: List[str] = ["llm", "tts", "stt", "assistant-stt"]


@pytest.mark.parametrize("subsystem", INVALID_PROVIDER_CASES)
def test_rejects_unsupported_runtime_providers(subsystem: str) -> None:
    client = make_client(object_handler)
    if subsystem == "llm":
        with pytest.raises(ValueError, match="llm.provider"):
            place_squad_call(
                client,
                llm=cast(RuntimeLlmInput, {"provider": "bogus", "model": "m"}),
                tts=valid_tts(),
                stt={"provider": "deepgram"},
            )
    elif subsystem == "tts":
        with pytest.raises(ValueError, match="tts.provider"):
            place_squad_call(
                client,
                llm=valid_llm(),
                tts=cast(
                    RuntimeTtsInput,
                    {"provider": "bogus", "model": "m", "voiceId": "v"},
                ),
                stt={"provider": "deepgram"},
            )
    elif subsystem == "stt":
        with pytest.raises(ValueError, match="stt.provider"):
            place_squad_call(
                client,
                llm=valid_llm(),
                tts=valid_tts(),
                stt=cast(CallSttConfig, {"provider": "bogus"}),
            )
    else:
        with pytest.raises(ValueError, match="stt.provider"):
            client.create_assistant(
                name="Assistant",
                stt=cast(AssistantSttConfig, {"provider": "bogus"}),
            )


@pytest.mark.parametrize("missing", ["model", "voiceId"])
def test_tts_requires_model_and_voice_id(missing: str) -> None:
    raw: Dict[str, object] = {
        "provider": "elevenlabs",
        "model": "eleven_turbo_v2_5",
        "voiceId": "voice-1",
    }
    del raw[missing]
    with pytest.raises(ValueError, match=f"tts.{missing}"):
        place_squad_call(
            make_client(object_handler),
            llm=valid_llm(),
            tts=cast(RuntimeTtsInput, raw),
            stt={"provider": "deepgram"},
        )


def test_tts_provider_specific_requirements() -> None:
    client = make_client(object_handler)
    place_squad_call(
        client,
        llm=valid_llm(),
        tts={"provider": "aws", "voiceId": "Filiz"},
        stt={"provider": "deepgram"},
    )
    place_squad_call(
        client,
        llm=valid_llm(),
        tts={"provider": "freya"},
        stt={"provider": "deepgram"},
    )
    with pytest.raises(ValueError, match="voiceId"):
        place_squad_call(
            client,
            llm=valid_llm(),
            tts=cast(RuntimeTtsInput, {"provider": "aws"}),
            stt={"provider": "deepgram"},
        )
    with pytest.raises(ValueError, match="not supported for AWS Polly"):
        place_squad_call(
            client,
            llm=valid_llm(),
            tts={"provider": "aws", "model": "bogus", "voiceId": "Filiz"},
            stt={"provider": "deepgram"},
        )


def test_llm_requires_model_and_call_stt_may_be_partial() -> None:
    client = make_client(object_handler)
    with pytest.raises(ValueError, match="llm.model"):
        place_squad_call(
            client,
            llm=cast(RuntimeLlmInput, {"provider": "openai"}),
            tts=valid_tts(),
            stt={"language": "tr"},
        )
    place_squad_call(
        client, llm=valid_llm(), tts=valid_tts(), stt={"language": "tr"}
    )


def test_assistant_rejects_silent_loss_inputs() -> None:
    client = make_client(object_handler)
    string_keywords = cast(
        AssistantSttConfig,
        {"provider": "deepgram", "keywords": ["OloVoice"]},
    )
    with pytest.raises(TypeError, match="entries must be objects"):
        client.create_assistant(name="Assistant", stt=string_keywords)

    thinking_string = cast(
        AssistantBackgroundAudio, {"thinking": "keyboard_typing"}
    )
    with pytest.raises(TypeError, match="thinking"):
        client.create_assistant(
            name="Assistant", background_audio=thinking_string
        )


def test_assistant_maps_snake_case_and_accepts_canonical_clips() -> None:
    bodies: List[Dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request_json(request))
        return httpx.Response(
            201,
            json={
                "success": True,
                "assistantId": "assistant-1",
                "warning": "readback unavailable",
            },
        )

    result = make_client(handler).create_assistant(
        name="Assistant",
        first_message="Merhaba",
        server_url="https://example.com/events",
        llm=valid_llm(),
        tts=valid_tts(),
        stt={"provider": "deepgram", "keywords": [{"phrase": "OloVoice"}]},
        background_audio={
            "ambient": "office_ambience",
            "thinking": {"builtin": "keyboard_typing", "volume": 0.2},
        },
    )
    assert result == {
        "success": True,
        "assistantId": "assistant-1",
        "warning": "readback unavailable",
    }
    assert bodies[0]["firstMessage"] == "Merhaba"
    assert bodies[0]["serverUrl"] == "https://example.com/events"
    assert "first_message" not in bodies[0]


def test_forward_compatible_extras_and_reserved_fields() -> None:
    bodies: List[Dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request_json(request))
        return httpx.Response(200, json={})

    client = make_client(handler)
    client.create_web_call(
        organization_id="org-1",
        assistant_id="assistant-1",
        futureOption={"enabled": True},
    )
    assert bodies[0]["futureOption"] == {"enabled": True}

    with pytest.raises(TypeError, match="reserved API field"):
        client.create_web_call(
            organization_id="org-1",
            assistant_id="assistant-1",
            organizationId="evil",
        )
    with pytest.raises(TypeError, match="lower camelCase"):
        client.create_web_call(
            organization_id="org-1",
            assistant_id="assistant-1",
            future_option=True,
        )


HttpScript = List[Tuple[bytes, float]]


class _ThreadedHttpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True
    scripts: List[HttpScript]
    calls: int
    script_lock: threading.Lock


class _ScriptedHttpHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        connection = cast(socket.socket, self.request)
        connection.settimeout(1.0)
        received = b""
        try:
            while b"\r\n\r\n" not in received and len(received) < 65536:
                part = connection.recv(4096)
                if not part:
                    return
                received += part
        except OSError:
            return

        server = cast(_ThreadedHttpServer, self.server)
        with server.script_lock:
            index = min(server.calls, len(server.scripts) - 1)
            server.calls += 1
            script = server.scripts[index]
        try:
            for chunk, delay_after in script:
                connection.sendall(chunk)
                if delay_after:
                    time.sleep(delay_after)
        except OSError:
            return


def _http_script(
    body: bytes,
    *,
    header_delay: float = 0.0,
    body_delay: float = 0.0,
    content_encoding: Optional[str] = None,
) -> HttpScript:
    headers = [
        b"HTTP/1.1 200 OK\r\n",
        f"Content-Length: {len(body)}\r\n".encode("ascii"),
        b"Content-Type: application/json\r\n",
        b"Connection: close\r\n",
    ]
    if content_encoding is not None:
        headers.append(f"Content-Encoding: {content_encoding}\r\n".encode("ascii"))
    header_bytes = b"".join(headers) + b"\r\n"
    header_chunks = (
        [(bytes((byte,)), header_delay) for byte in header_bytes]
        if header_delay
        else [(header_bytes, 0.0)]
    )
    body_chunks = (
        [(bytes((byte,)), body_delay) for byte in body]
        if body_delay
        else [(body, 0.0)]
    )
    return header_chunks + body_chunks


@contextmanager
def _scripted_http_server(
    scripts: List[HttpScript],
) -> Generator[Tuple[str, _ThreadedHttpServer], None, None]:
    server = _ThreadedHttpServer(("127.0.0.1", 0), _ScriptedHttpHandler)
    server.scripts = scripts
    server.calls = 0
    server.script_lock = threading.Lock()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = cast(Tuple[str, int], server.server_address)
    try:
        yield f"http://{host}:{port}", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class _KeepAliveHttpServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True
    closed_connections: int
    close_condition: threading.Condition


class _KeepAliveHttpHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        connection = cast(socket.socket, self.request)
        connection.settimeout(5.0)
        server = cast(_KeepAliveHttpServer, self.server)
        try:
            while True:
                received = b""
                while b"\r\n\r\n" not in received and len(received) < 65536:
                    part = connection.recv(4096)
                    if not part:
                        return
                    received += part
                body = b'{"success":true,"assistants":[]}'
                connection.sendall(
                    b"HTTP/1.1 200 OK\r\n"
                    + f"Content-Length: {len(body)}\r\n".encode("ascii")
                    + b"Content-Type: application/json\r\n"
                    + b"Connection: keep-alive\r\n\r\n"
                    + body
                )
        except OSError:
            return
        finally:
            with server.close_condition:
                server.closed_connections += 1
                server.close_condition.notify_all()


@contextmanager
def _keepalive_http_server(
) -> Generator[Tuple[str, _KeepAliveHttpServer], None, None]:
    server = _KeepAliveHttpServer(("127.0.0.1", 0), _KeepAliveHttpHandler)
    server.closed_connections = 0
    server.close_condition = threading.Condition()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = cast(Tuple[str, int], server.server_address)
    try:
        yield f"http://{host}:{port}", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def _wait_for_closed_connections(
    server: _KeepAliveHttpServer, count: int, timeout: float = 2.0
) -> bool:
    with server.close_condition:
        return server.close_condition.wait_for(
            lambda: server.closed_connections >= count,
            timeout=timeout,
        )


def _outbound_connections_to(port: int) -> Optional[int]:
    lsof = shutil.which("lsof")
    if lsof is None:
        return None
    result = subprocess.run(
        [lsof, "-nP", "-a", "-p", str(os.getpid()), "-iTCP"],
        check=False,
        capture_output=True,
        text=True,
    )
    endpoint = f"->127.0.0.1:{port}"
    return sum(endpoint in line for line in result.stdout.splitlines())


def _loop_thread_count() -> int:
    return sum(
        thread.is_alive() and thread.name == "olovoice-event-loop"
        for thread in threading.enumerate()
    )


def _fd_count() -> Optional[int]:
    for path in ("/dev/fd", "/proc/self/fd"):
        try:
            return len(os.listdir(path))
        except OSError:
            continue
    return None


def test_sync_total_deadline_covers_slow_plain_body() -> None:
    plain = b'{"success":true,"assistants":[]}'
    with _scripted_http_server(
        [_http_script(plain, body_delay=0.02)]
    ) as (base_url, _server):
        client = OloVoice(
            api_key="sk-test",
            base_url=base_url,
            timeout=0.05,
            max_retries=0,
            dangerously_allow_custom_base_url=True,
            dangerously_allow_insecure_http=True,
        )
        started = time.monotonic()
        try:
            with pytest.raises(APIConnectionError, match="timed out"):
                client.list_assistants()
        finally:
            client.close()
        elapsed = time.monotonic() - started
        assert 0.03 <= elapsed < 0.3


def test_sync_refuses_compressed_response_before_slow_body() -> None:
    body = gzip.compress(b'{"success":true,"assistants":[]}')
    with _scripted_http_server(
        [_http_script(body, body_delay=0.02, content_encoding="gzip")]
    ) as (base_url, _server):
        client = OloVoice(
            api_key="sk-test",
            base_url=base_url,
            timeout=0.05,
            max_retries=0,
            dangerously_allow_custom_base_url=True,
            dangerously_allow_insecure_http=True,
        )
        try:
            with pytest.raises(InvalidResponseError, match="Compressed response"):
                client.list_assistants()
        finally:
            client.close()


def test_sync_total_deadline_covers_headers_and_client_recovers() -> None:
    success = b'{"success":true,"assistants":[]}'
    with _scripted_http_server(
        [
            _http_script(success, header_delay=0.02),
            _http_script(success),
        ]
    ) as (base_url, server):
        client = OloVoice(
            api_key="sk-test",
            base_url=base_url,
            timeout=0.05,
            max_retries=0,
            dangerously_allow_custom_base_url=True,
            dangerously_allow_insecure_http=True,
        )
        started = time.monotonic()
        with pytest.raises(APIConnectionError, match="timed out"):
            client.list_assistants()
        assert time.monotonic() - started < 0.3
        assert client.list_assistants()["success"] is True
        assert server.calls == 2
        client.close()


def test_repeated_deadlines_do_not_leak_loop_threads_or_file_descriptors() -> None:
    gc.collect()
    baseline_threads = _loop_thread_count()
    baseline_fds = _fd_count()
    success = b'{"success":true,"assistants":[]}'
    with _scripted_http_server(
        [_http_script(success, header_delay=0.02)] * 3
    ) as (base_url, _server):
        client = OloVoice(
            api_key="sk-test",
            base_url=base_url,
            timeout=0.04,
            max_retries=0,
            dangerously_allow_custom_base_url=True,
            dangerously_allow_insecure_http=True,
        )
        assert _loop_thread_count() == baseline_threads + 1
        for _ in range(3):
            with pytest.raises(APIConnectionError):
                client.list_assistants()
            assert _loop_thread_count() == baseline_threads + 1
        client.close()
    gc.collect()
    assert _loop_thread_count() == baseline_threads
    final_fds = _fd_count()
    if baseline_fds is not None and final_fds is not None:
        assert final_fds <= baseline_fds + 2


def test_unclosed_sync_client_gc_stops_event_loop_thread() -> None:
    baseline = _loop_thread_count()
    client = make_client(object_handler)
    assert _loop_thread_count() == baseline + 1
    del client
    gc.collect()
    assert _loop_thread_count() == baseline


def test_sync_client_fork_registry_does_not_retain_closed_clients() -> None:
    gc.collect()
    baseline = len(client_module._SYNC_CLIENTS)
    for _ in range(200):
        client = make_client(object_handler)
        client.close()
    del client
    gc.collect()
    assert len(client_module._SYNC_CLIENTS) == baseline


def test_gc_finalizer_cannot_deadlock_a_new_runner_thread() -> None:
    script = """
import gc
import threading

import httpx

from olovoice import OloVoice


def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={}, request=request)


old = OloVoice(api_key="sk-test", transport=httpx.MockTransport(handler))
cycle = [old]
cycle.append(cycle)
del old, cycle
gc.disable()
original = threading.Thread._bootstrap_inner


def force_gc_before_started(thread: threading.Thread) -> None:
    gc.collect()
    original(thread)


threading.Thread._bootstrap_inner = force_gc_before_started
new = OloVoice(api_key="sk-test", transport=httpx.MockTransport(handler))
new.close()
"""
    result = subprocess.run(
        [sys.executable, "-u", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    assert result.returncode == 0, result.stderr


def test_gc_finalizer_on_its_own_runner_hands_cleanup_off_thread() -> None:
    script = """
import gc
import threading
import time

import httpx

from olovoice import OloVoice


def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={}, request=request)


client = OloVoice(api_key="sk-test", transport=httpx.MockTransport(handler))
holder = [client]
runner = client._runner
collected = threading.Event()


def collect_on_runner() -> None:
    holder.clear()
    gc.collect()
    collected.set()


runner._loop.call_soon_threadsafe(collect_on_runner)
del client
assert collected.wait(1.0)
deadline = time.monotonic() + 2.0
while runner._thread.is_alive() and time.monotonic() < deadline:
    time.sleep(0.01)
assert not runner._thread.is_alive()
assert not any(
    thread.name == "olovoice-cleanup" and thread.is_alive()
    for thread in threading.enumerate()
)
"""
    result = subprocess.run(
        [sys.executable, "-u", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    assert result.returncode == 0, result.stderr


def test_constructor_fork_and_gc_finalizer_cannot_form_a_wait_cycle() -> None:
    script = """
import gc
import os
import threading
import time

import httpx

from olovoice import OloVoice


def handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={}, request=request)


old = OloVoice(api_key="sk-test", transport=httpx.MockTransport(handler))
cycle = [old]
cycle.append(cycle)
del old, cycle
gc.disable()
bootstrap_entered = threading.Event()
allow_gc = threading.Event()
forced = threading.Event()
original = threading.Thread._bootstrap_inner


def force_gc_during_initialization(thread: threading.Thread) -> None:
    if thread.name == "olovoice-event-loop" and not forced.is_set():
        forced.set()
        bootstrap_entered.set()
        assert allow_gc.wait(1.0)
        gc.collect()
    original(thread)


threading.Thread._bootstrap_inner = force_gc_during_initialization
created = []
constructor = threading.Thread(
    target=lambda: created.append(
        OloVoice(api_key="sk-test", transport=httpx.MockTransport(handler))
    ),
    name="constructor",
)
constructor.start()
assert bootstrap_entered.wait(1.0)


def release_gc() -> None:
    time.sleep(0.05)
    allow_gc.set()


release = threading.Thread(target=release_gc, name="release-gc")
release.start()
child_pid = os.fork()
if child_pid == 0:
    os._exit(0)
waited_pid, status = os.waitpid(child_pid, 0)
constructor.join(1.0)
release.join(1.0)
assert waited_pid == child_pid
assert os.waitstatus_to_exitcode(status) == 0
assert not constructor.is_alive()
assert len(created) == 1
"""
    result = subprocess.run(
        [sys.executable, "-u", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    assert result.returncode == 0, result.stderr


def test_fork_cleanup_cancellation_gc_cannot_wait_on_its_own_gate() -> None:
    script = """
import asyncio
import gc
import threading

import httpx
import olovoice._client as client_module

from olovoice import OloVoice


def immediate(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={}, request=request)


gc.disable()
victim = OloVoice(api_key="sk-test", transport=httpx.MockTransport(immediate))
victim_resources = victim._resources
cycle = [victim]
cycle.append(cycle)
del victim, cycle
entered = threading.Event()


async def blocking(request: httpx.Request) -> httpx.Response:
    try:
        entered.set()
        await asyncio.Event().wait()
        return httpx.Response(200, json={}, request=request)
    finally:
        gc.collect()


outer = OloVoice(api_key="sk-test", transport=httpx.MockTransport(blocking))


class OrderedRegistry(set):
    def __iter__(self):
        return iter((outer._resources, victim_resources))


client_module._SYNC_CLIENTS = OrderedRegistry(
    (outer._resources, victim_resources)
)
caller = threading.Thread(target=lambda: outer.list_assistants())
caller.start()
assert entered.wait(1.0)
client_module._invalidate_sync_clients_before_fork()
client_module._finish_sync_clients_fork()
caller.join(1.0)
assert not caller.is_alive()
"""
    result = subprocess.run(
        [sys.executable, "-u", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        timeout=5.0,
    )
    assert result.returncode == 0, result.stderr


def test_timeout_get_retries_but_post_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: List[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    get_calls = 0

    async def get_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal get_calls
        get_calls += 1
        if get_calls == 1:
            await asyncio.Event().wait()
        return httpx.Response(200, json={"success": True, "assistants": []})

    get_client = make_client(get_handler, max_retries=1, timeout=0.02)
    assert get_client.list_assistants()["success"] is True
    assert get_calls == 2
    assert sleeps == [0.5]
    get_client.close()

    post_calls = 0

    async def post_handler(_request: httpx.Request) -> httpx.Response:
        nonlocal post_calls
        post_calls += 1
        await asyncio.Event().wait()
        return httpx.Response(200, json={})

    post_client = make_client(post_handler, max_retries=4, timeout=0.02)
    with pytest.raises(APIConnectionError):
        post_client.create_lead(name="Ada", phone="+905551234567")
    assert post_calls == 1
    post_client.close()


class _OversizedAsyncStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        for _ in range(33):
            yield b"x" * 65536


class _FailingAsyncStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"{"
        raise httpx.ReadError("stream failed")


class _TrackingCompressedStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.iterated = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        self.iterated = True
        yield self.content


def test_declared_and_streamed_response_size_caps() -> None:
    def declared(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-length": str(2 * 1024 * 1024 + 1)},
            content=b"{}",
        )

    with pytest.raises(InvalidResponseError, match="exceeded"):
        make_client(declared, max_retries=0).list_assistants()

    def streamed(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_OversizedAsyncStream())

    with pytest.raises(InvalidResponseError, match="exceeded"):
        make_client(streamed, max_retries=0).list_assistants()


def test_compressed_bomb_is_rejected_without_reading_the_stream() -> None:
    stream = _TrackingCompressedStream(gzip.compress(b"x" * (3 * 1024 * 1024)))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            stream=stream,
        )

    with pytest.raises(InvalidResponseError, match="Compressed response"):
        make_client(handler, max_retries=0).list_assistants()
    assert stream.iterated is False


def test_stream_failure_preserves_response_metadata() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-request-id": "req-stream", "retry-after": "7"},
            stream=_FailingAsyncStream(),
        )

    with pytest.raises(APIConnectionError) as info:
        make_client(handler, max_retries=0).list_assistants()
    assert info.value.status == 200
    assert info.value.request_id == "req-stream"
    assert info.value.retry_after == 7.0


INVALID_SUCCESS_CASES: List[Tuple[int, bytes, Mapping[str, str]]] = [
    (204, b"", {"x-request-id": "req-empty"}),
    (200, b"not json", {"content-type": "text/plain"}),
    (200, b"[]", {"content-type": "application/json"}),
    (200, b"true", {"content-type": "application/json"}),
]


@pytest.mark.parametrize("status,body,headers", INVALID_SUCCESS_CASES)
def test_success_must_be_a_json_object(
    status: int, body: bytes, headers: Mapping[str, str]
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers=headers)

    with pytest.raises(InvalidResponseError) as info:
        make_client(handler, max_retries=0).list_assistants()
    assert info.value.status == status
    if status == 204:
        assert info.value.request_id == "req-empty"


def test_non_json_error_body_is_bounded() -> None:
    text = "failure-" * 1000

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=text)

    with pytest.raises(InternalServerError) as info:
        make_client(handler, max_retries=0).list_assistants()
    assert isinstance(info.value.body, str)
    assert len(info.value.body) <= 2051
    assert str(info.value).endswith("...")


def test_redirect_is_refused_without_following() -> None:
    seen: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            307,
            headers={"location": "https://evil.example/steal"},
            json={"error": "redirect"},
        )

    with pytest.raises(InvalidResponseError, match="Redirect response refused"):
        make_client(handler, max_retries=0).list_assistants()
    assert seen == ["https://api.olovoice.ai/assistants"]


INVALID_BASE_URLS: List[Tuple[str, bool, bool]] = [
    ("https://staging.example", False, False),
    ("http://api.olovoice.ai", True, True),
    ("https://user:secret@api.olovoice.ai", False, False),
    ("https://api.olovoice.ai/v1", False, False),
    ("https://api.olovoice.ai?tenant=evil", False, False),
    ("https://api.olovoice.ai#fragment", False, False),
    ("ftp://api.olovoice.ai", True, False),
    ("https://api.olovoice.ai:444", False, False),
]


@pytest.mark.parametrize("base_url,allow_custom,allow_http", INVALID_BASE_URLS)
def test_rejects_unsafe_base_urls(
    base_url: str, allow_custom: bool, allow_http: bool
) -> None:
    with pytest.raises(ValueError):
        OloVoice(
            api_key="sk-test",
            base_url=base_url,
            dangerously_allow_custom_base_url=allow_custom,
            dangerously_allow_insecure_http=allow_http,
        )


VALID_BASE_URLS: List[Tuple[str, bool]] = [
    ("https://staging.example", False),
    ("http://127.0.0.1:8080", True),
    ("http://localhost:8080", True),
    ("http://[::1]:8080", True),
]


@pytest.mark.parametrize("base_url,insecure", VALID_BASE_URLS)
def test_allows_explicit_safe_custom_base_urls(base_url: str, insecure: bool) -> None:
    client = OloVoice(
        api_key="sk-test",
        base_url=base_url,
        dangerously_allow_custom_base_url=True,
        dangerously_allow_insecure_http=insecure,
        transport=httpx.MockTransport(object_handler),
    )
    assert client.base_url == base_url
    client.close()


PROTECTED_HEADERS: List[str] = [
    "Authorization",
    "AUTHORIZATION",
    "Content-Type",
    "Accept",
    "Accept-Encoding",
    "User-Agent",
    "Cookie",
    "Proxy-Authorization",
    "Connection",
    "Host",
    "Content-Length",
    "Transfer-Encoding",
]


@pytest.mark.parametrize("header", PROTECTED_HEADERS)
def test_rejects_case_insensitive_protected_header_overrides(header: str) -> None:
    with pytest.raises(ValueError, match="may not override"):
        OloVoice(api_key="sk-test", default_headers={header: "evil"})


def test_safe_custom_header_and_secret_safe_repr() -> None:
    seen: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"success": True, "assistants": []})

    secret = "sk-super-secret-value"
    client = OloVoice(
        api_key=secret,
        default_headers={"X-Correlation-Id": "corr-1"},
        transport=httpx.MockTransport(handler),
    )
    assert client.list_assistants()["success"] is True
    assert seen[0].headers["x-correlation-id"] == "corr-1"
    assert seen[0].headers["accept-encoding"] == "identity"
    assert secret not in repr(client)
    assert secret not in repr(vars(client))
    assert secret not in repr(vars(client._async_client))
    assert "_api_key" not in vars(client)
    assert "_headers" not in vars(client)
    client.close()


INVALID_TIMEOUTS: List[object] = [0, -1, float("nan"), float("inf"), True, "30"]


@pytest.mark.parametrize("timeout", INVALID_TIMEOUTS)
def test_rejects_invalid_timeout(timeout: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        OloVoice(api_key="sk-test", timeout=cast(float, timeout))


@pytest.mark.parametrize("max_retries", [-1, True])
def test_rejects_invalid_max_retries(max_retries: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        OloVoice(api_key="sk-test", max_retries=cast(int, max_retries))


class _SyncOnlyTransport(httpx.BaseTransport):
    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={}, request=request)


class _PidRecordingTransport(httpx.AsyncBaseTransport):
    def __init__(self) -> None:
        self.closed_in: List[int] = []

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        return httpx.Response(
            200,
            json={"success": True, "assistants": []},
            request=request,
        )

    async def aclose(self) -> None:
        self.closed_in.append(os.getpid())


def test_sync_facade_rejects_sync_only_custom_transport() -> None:
    transport = _SyncOnlyTransport()
    with pytest.raises(TypeError, match="AsyncBaseTransport"):
        OloVoice(
            api_key="sk-test",
            transport=cast(httpx.AsyncBaseTransport, transport),
        )
    transport.close()


def test_async_client_rejects_sync_only_custom_transport() -> None:
    transport = _SyncOnlyTransport()
    with pytest.raises(TypeError, match="AsyncBaseTransport"):
        AsyncOloVoice(
            api_key="sk-test",
            transport=cast(httpx.AsyncBaseTransport, transport),
        )
    transport.close()


def test_client_options_are_read_only_for_sync_and_async() -> None:
    sync_client = make_client(object_handler, max_retries=1, timeout=3.0)
    async_client = make_async_client(object_handler, max_retries=1, timeout=3.0)
    try:
        for client in (sync_client, async_client):
            with pytest.raises(AttributeError):
                setattr(client, "base_url", "https://evil.example")
            with pytest.raises(AttributeError):
                setattr(client, "timeout", 0.01)
            with pytest.raises(AttributeError):
                setattr(client, "max_retries", 0)
            assert client.base_url == "https://api.olovoice.ai"
            assert client.timeout == 3.0
            assert client.max_retries == 1
    finally:
        sync_client.close()
        asyncio.run(async_client.close())


@pytest.mark.parametrize("call_id", ["slash/value", "100%", "what?", "#hash", "Türkçe"])
def test_path_segments_are_encoded_in_sync_and_async_clients(call_id: str) -> None:
    paths: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.raw_path.decode("ascii").split("?", 1)[0])
        return httpx.Response(200, json={})

    sync_client = make_client(handler)
    sync_client.get_call_log(call_id)
    sync_client.close()

    async def run() -> None:
        async_client = make_async_client(handler)
        try:
            await async_client.get_call_log(call_id)
        finally:
            await async_client.close()

    asyncio.run(run())
    expected = "/call-logs/" + quote(call_id, safe="")
    assert paths == [expected, expected]


def test_query_omits_none_and_encodes_unicode() -> None:
    requests: List[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    client = make_client(handler)
    client.list_call_logs(organization_id="org / Türkçe")
    client.close()
    params = requests[0].url.params
    assert dict(params) == {"organizationId": "org / Türkçe"}
    assert "limit" not in str(requests[0].url)
    assert "%2F" in str(requests[0].url)


def test_sync_async_public_method_signature_parity() -> None:
    methods = [
        "create_call",
        "create_web_call",
        "list_call_logs",
        "get_call_log",
        "refresh_recording_url",
        "list_assistants",
        "create_assistant",
        "get_assistant",
        "update_assistant",
        "delete_assistant",
        "create_lead",
        "get_metrics",
    ]
    for method in methods:
        sync_parameters = inspect.signature(getattr(OloVoice, method)).parameters
        async_parameters = inspect.signature(getattr(AsyncOloVoice, method)).parameters
        assert list(sync_parameters) == list(async_parameters)
        for name in sync_parameters:
            assert sync_parameters[name].kind == async_parameters[name].kind
            assert sync_parameters[name].default == async_parameters[name].default


@pytest.mark.parametrize(
    "retry_after,expected",
    [("12", 12.0), ("not-a-date", 0.5)],
)
def test_sync_retry_after_seconds_and_invalid_fallback(
    retry_after: str,
    expected: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: List[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record_sleep)
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"retry-after": retry_after},
                json={"error": "slow down"},
            )
        return httpx.Response(200, json={"success": True, "assistants": []})

    client = make_client(handler, max_retries=1, timeout=0.02)
    assert client.list_assistants()["success"] is True
    assert sleeps == [expected]
    client.close()


def test_async_retry_after_http_date(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: List[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record_sleep)
    retry_at = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30))
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"retry-after": retry_at},
                json={"error": "slow down"},
            )
        return httpx.Response(200, json={"success": True, "assistants": []})

    async def run() -> None:
        client = make_async_client(handler, max_retries=1, timeout=0.02)
        try:
            assert (await client.list_assistants())["success"] is True
        finally:
            await client.close()

    asyncio.run(run())
    assert len(sleeps) == 1
    assert 28.0 <= sleeps[0] <= 30.0


def test_final_rate_limit_error_exposes_retry_after() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"retry-after": "9", "x-request-id": "req-rate"},
            json={"error": "slow down"},
        )

    with pytest.raises(RateLimitError) as info:
        make_client(handler, max_retries=0).list_assistants()
    assert info.value.retry_after == 9.0
    assert info.value.request_id == "req-rate"


def test_unicode_retry_after_falls_back_in_sync_and_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: List[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record_sleep)

    def handler_factory() -> Handler:
        calls = 0

        def handler(_request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(
                    429,
                    headers=[(b"retry-after", b"\xb2")],
                    json={"error": "slow down"},
                )
            return httpx.Response(200, json={"success": True, "assistants": []})

        return handler

    sync_client = make_client(handler_factory(), max_retries=1)
    assert sync_client.list_assistants()["success"] is True
    sync_client.close()

    async def run() -> None:
        client = make_async_client(handler_factory(), max_retries=1)
        try:
            assert (await client.list_assistants())["success"] is True
        finally:
            await client.close()

    asyncio.run(run())
    assert sleeps == [0.5, 0.5]


def test_compressed_and_oversized_server_errors_retry_with_typed_final_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: List[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(asyncio, "sleep", record_sleep)
    calls = 0

    def compressed_then_success(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                503,
                headers={"content-encoding": "gzip", "retry-after": "2"},
                stream=_TrackingCompressedStream(
                    gzip.compress(b'{"error":"unavailable"}')
                ),
            )
        return httpx.Response(200, json={"success": True, "assistants": []})

    client = make_client(compressed_then_success, max_retries=1)
    assert client.list_assistants()["success"] is True
    client.close()
    assert calls == 2
    assert sleeps == [2.0]

    def oversized(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            503,
            headers={
                "content-length": str(2 * 1024 * 1024 + 1),
                "retry-after": "3",
                "x-request-id": "req-large",
            },
            content=b"{}",
        )

    with pytest.raises(InternalServerError) as info:
        make_client(oversized, max_retries=0).list_assistants()
    assert info.value.status == 503
    assert info.value.retry_after == 3.0
    assert info.value.request_id == "req-large"
    assert "exceeded" in str(info.value)


def test_success_protocol_error_does_not_chain_itself() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            content=gzip.compress(b'{"success":true}'),
        )

    client = make_client(handler, max_retries=0)
    try:
        with pytest.raises(InvalidResponseError) as info:
            client.list_assistants()
    finally:
        client.close()
    assert info.value.__cause__ is None

    async def run() -> None:
        async_client = make_async_client(handler, max_retries=0)
        try:
            with pytest.raises(InvalidResponseError) as async_info:
                await async_client.list_assistants()
        finally:
            await async_client.close()
        assert async_info.value.__cause__ is None

    asyncio.run(run())


def test_parse_deadline_retries_get_but_not_post_sync_and_async(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_json = httpx.Response.json
    parse_calls = 0

    def delayed_first_json(
        response: httpx.Response, **kwargs: object
    ) -> object:
        nonlocal parse_calls
        parse_calls += 1
        if parse_calls == 1:
            time.sleep(0.03)
        return cast(object, original_json(response, **kwargs))

    sleeps: List[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(httpx.Response, "json", delayed_first_json)
    monkeypatch.setattr(asyncio, "sleep", record_sleep)
    transport_calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal transport_calls
        transport_calls += 1
        return httpx.Response(200, json={"success": True, "assistants": []})

    sync_client = make_client(handler, max_retries=1, timeout=0.01)
    assert sync_client.list_assistants()["success"] is True
    sync_client.close()
    assert transport_calls == 2

    parse_calls = 0
    transport_calls = 0

    async def run_get() -> None:
        client = make_async_client(handler, max_retries=1, timeout=0.01)
        try:
            assert (await client.list_assistants())["success"] is True
        finally:
            await client.close()

    asyncio.run(run_get())
    assert transport_calls == 2

    parse_calls = 0
    transport_calls = 0
    post_client = make_client(handler, max_retries=4, timeout=0.01)
    with pytest.raises(APIConnectionError):
        post_client.create_lead(name="Ada", phone="+905551234567")
    post_client.close()
    assert transport_calls == 1


def test_unreadable_401_is_typed_and_never_retried_sync_and_async() -> None:
    class FailingUnauthorizedStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            raise httpx.ReadError("truncated unauthorized response")
            yield b""  # pragma: no cover

    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            401,
            headers={"x-request-id": "req-auth"},
            stream=FailingUnauthorizedStream(),
        )

    with pytest.raises(AuthenticationError) as sync_info:
        make_client(handler, max_retries=3).list_assistants()
    assert calls == 1
    assert sync_info.value.request_id == "req-auth"

    calls = 0

    async def run() -> None:
        client = make_async_client(handler, max_retries=3)
        try:
            with pytest.raises(AuthenticationError):
                await client.list_assistants()
        finally:
            await client.close()

    asyncio.run(run())
    assert calls == 1

    calls = 0

    def compressed_unauthorized(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            401,
            headers={
                "content-encoding": "gzip",
                "x-request-id": "req-compressed-auth",
            },
            content=gzip.compress(b'{"error":"unauthorized"}'),
        )

    with pytest.raises(AuthenticationError) as compressed_info:
        make_client(compressed_unauthorized, max_retries=3).list_assistants()
    assert calls == 1
    assert compressed_info.value.request_id == "req-compressed-auth"


def test_concurrent_close_cancels_inflight_sync_request() -> None:
    entered = threading.Event()
    cleanup_done = threading.Event()
    errors: List[BaseException] = []

    async def handler(_request: httpx.Request) -> httpx.Response:
        try:
            entered.set()
            await asyncio.Event().wait()
            return httpx.Response(200, json={})
        finally:
            await asyncio.sleep(0.05)
            cleanup_done.set()

    client = make_client(handler, max_retries=0, timeout=30.0)

    def request() -> None:
        try:
            client.list_assistants()
        except BaseException as exc:
            errors.append(exc)

    caller = threading.Thread(target=request)
    caller.start()
    assert entered.wait(timeout=1.0)
    client.close()
    caller.join(timeout=1.0)
    assert caller.is_alive() is False
    assert len(errors) == 1
    assert cleanup_done.is_set()
    with pytest.raises(RuntimeError, match="closed"):
        client.list_assistants()


def test_concurrent_close_waits_for_the_first_cleanup_to_finish() -> None:
    entered = threading.Event()
    cleanup_started = threading.Event()
    cleanup_done = threading.Event()
    caller_errors: List[BaseException] = []
    close_errors: List[BaseException] = []

    async def handler(_request: httpx.Request) -> httpx.Response:
        try:
            entered.set()
            await asyncio.Event().wait()
            return httpx.Response(200, json={})
        finally:
            cleanup_started.set()
            await asyncio.sleep(0.2)
            cleanup_done.set()

    client = make_client(handler, max_retries=0, timeout=30.0)

    def request() -> None:
        try:
            client.list_assistants()
        except BaseException as exc:
            caller_errors.append(exc)

    def close() -> None:
        try:
            client.close()
        except BaseException as exc:
            close_errors.append(exc)

    caller = threading.Thread(target=request)
    first_close = threading.Thread(target=close)
    second_close = threading.Thread(target=close)
    caller.start()
    assert entered.wait(timeout=1.0)
    first_close.start()
    assert cleanup_started.wait(timeout=1.0)
    second_close.start()
    second_close.join(timeout=0.05)
    assert second_close.is_alive()
    assert cleanup_done.wait(timeout=1.0)
    first_close.join(timeout=1.0)
    second_close.join(timeout=1.0)
    caller.join(timeout=1.0)
    assert not first_close.is_alive()
    assert not second_close.is_alive()
    assert not caller.is_alive()
    assert close_errors == []
    assert len(caller_errors) == 1
    assert not client._runner._thread.is_alive()


def test_close_does_not_deadlock_when_cancellation_runs_gc_finalizer() -> None:
    gc.collect()
    baseline_threads = _loop_thread_count()
    gc.disable()
    try:
        inner = make_client(object_handler)
        cycle: List[object] = [inner]
        cycle.append(cycle)
        del inner, cycle

        entered = threading.Event()
        errors: List[BaseException] = []

        async def handler(_request: httpx.Request) -> httpx.Response:
            try:
                entered.set()
                await asyncio.Event().wait()
                return httpx.Response(200, json={})
            finally:
                gc.collect()

        outer = make_client(handler, max_retries=0, timeout=30.0)

        def request() -> None:
            try:
                outer.list_assistants()
            except BaseException as exc:
                errors.append(exc)

        caller = threading.Thread(target=request)
        caller.start()
        assert entered.wait(timeout=1.0)
        started = time.monotonic()
        outer.close()
        assert time.monotonic() - started < 1.0
        caller.join(timeout=1.0)
        assert caller.is_alive() is False
        assert len(errors) == 1
    finally:
        gc.enable()
        gc.collect()
    assert _loop_thread_count() == baseline_threads


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires os.fork")
def test_sync_client_rejects_reuse_after_fork() -> None:
    with _keepalive_http_server() as (base_url, server):
        _, server_port = cast(Tuple[str, int], server.server_address)
        client = OloVoice(
            api_key="sk-test",
            base_url=base_url,
            max_retries=0,
            dangerously_allow_custom_base_url=True,
            dangerously_allow_insecure_http=True,
        )
        assert client.list_assistants()["success"] is True

        read_fd, write_fd = os.pipe()
        child_pid = os.fork()
        if child_pid == 0:
            os.close(read_fd)
            fds_before = _fd_count()
            try:
                client.list_assistants()
            except RuntimeError as exc:
                inherited_error = str(exc)
            else:
                inherited_error = "no error"
            inherited_connections = _outbound_connections_to(server_port)
            child_client = OloVoice(
                api_key="sk-test",
                base_url=base_url,
                max_retries=0,
                dangerously_allow_custom_base_url=True,
                dangerously_allow_insecure_http=True,
            )
            try:
                child_success = child_client.list_assistants()["success"]
            finally:
                child_client.close()
            child_result = json.dumps(
                {
                    "error": inherited_error,
                    "fdsBefore": fds_before,
                    "fdsAfter": _fd_count(),
                    "inheritedConnections": inherited_connections,
                    "loopClosed": client._runner._loop.is_closed(),
                    "newClientSuccess": child_success,
                }
            ).encode("utf-8")
            os.write(write_fd, child_result)
            os.close(write_fd)
            os._exit(0)

        os.close(write_fd)
        child_payload = cast(
            Dict[str, object], json.loads(os.read(read_fd, 4096).decode("utf-8"))
        )
        os.close(read_fd)
        waited_pid, status = os.waitpid(child_pid, 0)
        assert waited_pid == child_pid
        assert os.waitstatus_to_exitcode(status) == 0
        assert "fork invalidated" in str(child_payload["error"])
        assert child_payload["loopClosed"] is True
        assert child_payload["newClientSuccess"] is True
        inherited_connection_result = child_payload["inheritedConnections"]
        if isinstance(inherited_connection_result, int):
            assert inherited_connection_result == 0
        child_fds_before = child_payload["fdsBefore"]
        child_fds_after = child_payload["fdsAfter"]
        if isinstance(child_fds_before, int) and isinstance(child_fds_after, int):
            assert child_fds_after <= child_fds_before + 1

        with pytest.raises(RuntimeError, match="fork invalidated"):
            client.list_assistants()
        assert client._runner._loop.is_closed()
        parent_client = OloVoice(
            api_key="sk-test",
            base_url=base_url,
            max_retries=0,
            dangerously_allow_custom_base_url=True,
            dangerously_allow_insecure_http=True,
        )
        try:
            assert parent_client.list_assistants()["success"] is True
        finally:
            parent_client.close()
        assert _wait_for_closed_connections(server, 3)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires os.fork")
def test_fork_never_closes_inherited_transport_from_child() -> None:
    parent_pid = os.getpid()
    transport = _PidRecordingTransport()
    client = OloVoice(api_key="sk-test", transport=transport, max_retries=0)
    assert client.list_assistants()["success"] is True
    read_fd, write_fd = os.pipe()
    child_pid = os.fork()
    if child_pid == 0:
        os.close(read_fd)
        try:
            client.list_assistants()
        except RuntimeError:
            inherited_client_failed = True
        else:
            inherited_client_failed = False
        client.close()
        os.write(
            write_fd,
            json.dumps(
                {
                    "closedIn": transport.closed_in,
                    "inheritedClientFailed": inherited_client_failed,
                }
            ).encode("utf-8"),
        )
        os.close(write_fd)
        os._exit(0)

    os.close(write_fd)
    child_result = cast(
        Dict[str, object], json.loads(os.read(read_fd, 4096))
    )
    os.close(read_fd)
    waited_pid, status = os.waitpid(child_pid, 0)
    assert waited_pid == child_pid
    assert os.waitstatus_to_exitcode(status) == 0
    assert child_result["closedIn"] == [parent_pid]
    assert child_result["inheritedClientFailed"] is True
    assert transport.closed_in == [parent_pid]


def test_deep_json_never_leaks_recursion_error_sync_or_async() -> None:
    nested = ("[" * 1200 + "{}" + "]" * 1200).encode("ascii")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=nested,
            headers={"content-type": "application/json"},
        )

    with pytest.raises(InvalidResponseError):
        make_client(handler, max_retries=0).list_assistants()

    async def run() -> None:
        client = make_async_client(handler, max_retries=0)
        try:
            with pytest.raises(InvalidResponseError):
                await client.list_assistants()
        finally:
            await client.close()

    asyncio.run(run())


def test_call_log_required_wire_shape_and_sanitized_absences() -> None:
    log: CallLog = {
        "id": "row-1",
        "callId": "call-1",
        "assistantId": None,
        "assistantName": None,
        "idempotencyKey": None,
        "callType": "outbound",
        "status": "ended",
        "startedAt": "2026-08-10T00:00:00Z",
        "endedAt": None,
        "endReason": None,
        "durationSeconds": None,
        "customerName": None,
        "customerPhone": None,
        "organizationPhoneNumber": None,
        "phoneNumberProvider": None,
        "recordingUrl": None,
        "recordingAssistantUrl": None,
        "recordingCustomerUrl": None,
        "artifactSuppressedReason": None,
        "firstMessage": None,
        "mainPrompt": None,
        "serverUrl": None,
        "analysisSummary": None,
        "analysisSuccess": None,
        "analysisScore": None,
        "analysisSentiment": None,
        "analysisReasons": None,
        "analysisStatus": None,
        "analysisError": None,
        "analysisStartedAt": None,
        "analysisCompletedAt": None,
        "ruleSuccessCount": 0,
        "ruleFailureCount": 0,
        "rulePartialCount": 0,
        "costCurrency": None,
        "costTotal": None,
        "toolRuns": None,
        "analysis": None,
        "aiDisclosures": {
            "transcript": {
                "label": "AI-transcribed",
                "source": "stt",
                "provider": None,
                "model": None,
            }
        },
        "artifact": None,
        "timeline": None,
        "ruleChecklist": None,
        "structuredOutputs": [
            {
                "id": "result-1",
                "structuredOutputId": "definition-1",
                "name": None,
                "description": None,
                "status": None,
                "result": ["scalar", 1, None],
                "errorMessage": None,
                "provider": None,
                "model": None,
                "latencyMs": None,
                "tokensUsed": None,
                "createdAt": None,
                "updatedAt": None,
            }
        ],
        "metadata": None,
        "payload": None,
        "publicPayload": None,
        "history": [
            {
                "timestamp": "2026-08-10T00:00:00Z",
                "level": "Info",
                "category": "Transcript",
                "message": "hello",
                "raw": {"role": "assistant"},
            }
        ],
        "createdAt": "2026-08-10T00:00:00Z",
        "updatedAt": "2026-08-10T00:00:00Z",
    }
    required = cast(FrozenSet[str], getattr(CallLog, "__required_keys__"))
    assert set(log) == set(required)
    assert not {
        "metricsSummary",
        "latencySummary",
        "costBreakdown",
        "metricsLog",
        "ologuard",
    } & set(required)


def test_metrics_response_matches_dashboard_shape_without_phantom_keys() -> None:
    latency: LatencyBreakdown = {
        "avgTurnEndDelayMs": 1.0,
        "avgLlmTtftMs": 2.0,
        "avgRealtimeTtftMs": 0.0,
        "avgTtsTtfbMs": 3.0,
        "avgPlaybackLatencyMs": 4.0,
        "avgTotalLatencyMs": 10.0,
        "sampleCount": 1,
        "dominantSource": "llm",
        "dominantLabel": "LLM TTFT",
    }
    metrics: MetricsResponse = {
        "summary": {
            "totalCalls": 1,
            "totalDuration": 10.0,
            "totalCost": 0.1,
            "successRate": 100.0,
            "analysisCoverage": 100.0,
            "answeredRate": 100.0,
            "answeredCalls": 1,
            "analyzedCalls": 1,
            "pendingAnalysisCalls": 0,
            "ruleCompliance": 100.0,
            "totalInputTokens": 10.0,
            "totalOutputTokens": 5.0,
            "avgLatencyMs": 10.0,
            "latencyBreakdown": latency,
            "currency": None,
            "rules": {"passed": 1, "partial": 0, "failed": 0, "checked": 1},
        },
        "trends": [
            {
                "date": "2026-08-10",
                "calls": 1,
                "cost": 0.1,
                "success": 1,
                "successAnalyzed": 1,
                "analyzed": 1,
                "inputTokens": 10.0,
                "outputTokens": 5.0,
                "avgLatencyMs": 10.0,
                "latencySampleCount": 1,
                "avgLatency": 10.0,
                "latencyBreakdown": latency,
                "successRate": 100.0,
            }
        ],
        "hourlyActivity": [{"hour": 9, "calls": 1}],
        "durationDistribution": [{"range": "0-30", "count": 1}],
        "disconnectReasons": [{"reason": "completed", "count": 1}],
        "sentimentAnalysis": [{"name": "Pozitif", "value": 1, "color": "#fff"}],
        "funnel": {"initiated": 1, "answered": 1, "success": 1},
        "topAssistants": [
            {
                "id": "assistant-1",
                "name": "Support",
                "calls": 1,
                "answeredRate": 100.0,
                "analysisCoverage": 100.0,
                "successRate": 100.0,
                "avgDuration": 10.0,
                "totalCost": 0.1,
                "avgCost": 0.1,
                "totalInputTokens": 10.0,
                "totalOutputTokens": 5.0,
                "avgLatency": 10.0,
                "latencyBreakdown": latency,
                "ruleCompliance": 100.0,
            }
        ],
        "toolUsage": [{"name": "lookup", "count": 1, "success": 1, "fail": 0}],
    }
    annotations = cast(Dict[str, object], getattr(MetricsResponse, "__annotations__"))
    assert set(metrics) == set(annotations)
    assert not {"timeline", "assistants", "range"} & set(annotations)
