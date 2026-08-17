# olovoice — Python SDK (pre-release)

Typed synchronous and asynchronous clients for the [olovoice Public API](https://docs.olovoice.ai), built on `httpx` for Python 3.11+.

> This package has not been published to or reserved on PyPI yet. Install it only from a trusted local checkout or an internally verified release artifact. Do not rely on `pip install olovoice` until an official release is announced.

## Install from this checkout

From the SDK repository root:

```bash
python -m pip install -e ./python
```

Or, from this directory:

```bash
python -m pip install -e .
```

Set the API key in your server environment:

```bash
export OLOVOICE_API_KEY="YOUR_API_KEY"
```

Never expose this key in browser or mobile application code.

## Complete outbound-call example

`/call` needs runtime configuration in addition to IDs. This classic, non-realtime example includes every required section for a direct assistant call:

```python
from olovoice import OloVoice

with OloVoice() as client:  # reads OLOVOICE_API_KEY
    call = client.create_call(
        assistant_id="YOUR_ASSISTANT_ID",
        phone_number_id="YOUR_PHONE_NUMBER_ID",
        customer={"number": "+905551234567", "name": "Kemal"},
        first_message="Merhaba, OloVoice asistanınız arıyor.",
        content="Kullanıcıya yardımcı ol ve sorularını kısa biçimde yanıtla.",
        llm={"provider": "openai", "model": "gpt-4o-mini"},
        tts={
            "provider": "elevenlabs",
            "model": "eleven_turbo_v2_5",
            "voiceId": "YOUR_VOICE_ID",
        },
        stt={"provider": "deepgram", "model": "nova-3", "language": "tr"},
        conversation={},
        background_audio={},
    )

    call_id = call["payload"]["callId"]
    log = client.get_call_log(call_id)
    print(log["data"]["status"])
```

The API can return accepted, skipped, or duplicate carrier results. Check optional carrier fields before assuming a phone leg was placed:

```python
carrier = call["carrier"]
if isinstance(carrier, dict):
    if carrier.get("skipped") or carrier.get("duplicate"):
        print(carrier.get("reason", "Carrier did not start a new phone leg"))
else:
    print("Carrier returned a non-object value:", carrier)
```

## Web call and async client

For `/web-call`, stored assistant configuration is hydrated when optional runtime configs are omitted. A minimal direct-assistant request is therefore valid:

```python
import asyncio

from olovoice import AsyncOloVoice


async def main() -> None:
    async with AsyncOloVoice() as client:
        session = await client.create_web_call(
            organization_id="YOUR_ORGANIZATION_ID",
            assistant_id="YOUR_ASSISTANT_ID",
        )
        print(session["callId"], session["connectionUrl"])


asyncio.run(main())
```

Run this on your backend. Send only the returned short-lived `token` and `connectionUrl` to your frontend WebRTC client.

## Call configuration rules

- `create_call` always requires `phone_number_id`, `customer.number`, `llm`, `conversation`, and `background_audio`, plus at least one of `assistant_id`, `squad_id`, or `workflow_id`.
- A plain direct `assistant_id` call also requires `first_message` and `content`. A selected squad or workflow can supply those values. Multiple selectors are accepted; they are not an exclusive-or.
- A classic LLM call requires both `tts` and `stt`.
- OpenAI Realtime `halfCascade` requires `tts` but not `stt`.
- OpenAI Realtime `nativeAudio` requires neither `tts` nor `stt`; the server may reject it when the native-audio rollout flag is disabled.
- Realtime classification follows the API: provider aliases `openai-realtime`, `openai_realtime`, and `openai.realtime`, or provider `openai` with model `gpt-realtime`, `gpt-realtime-1.5`, or `gpt-realtime-2`.
- Supplied `llm` objects require a supported `provider` and a non-empty `model`. ElevenLabs and OpenAI `tts` require `provider`, `model`, and `voiceId`; AWS/Polly requires `provider` and `voiceId` while `model` is optional; Freya and Nova aliases allow provider-only configuration because their runtime defaults supply model and voice. Call/web-call `stt` may be a partial override because it is merged with stored settings, but a supplied provider must be supported. Assistant create/update `stt` requires a supported `provider`.
- Call-time STT keywords may be strings or `{ "phrase": ..., "boost": ... }` objects. Assistant STT keywords must be keyword objects; `boost` may be omitted or `None`. Call-time background-audio clips may use string shorthands. Assistant `ambient` accepts a string shorthand or clip object, while assistant `thinking` must be a clip object such as `{ "builtin": "keyboard_typing", "volume": 0.2 }`.

## Naming and forward-compatible fields

Top-level method arguments use Python `snake_case`; the SDK maps them to canonical API `camelCase` keys. Nested API objects already use canonical camelCase:

```python
client.create_assistant(
    name="Destek",
    first_message="Merhaba!",
    content="Destek taleplerini çöz.",
    server_url="https://example.com/call-events",
    llm={"provider": "openai", "model": "gpt-4o-mini", "maxTokens": 600},
    background_audio={
        "thinking": {"builtin": "keyboard_typing", "volume": 0.15}
    },
)
```

Unknown future top-level fields can be passed as lower-camel-case keyword arguments. The SDK rejects snake_case extras and prevents extras from overriding canonical or reserved keys:

```python
client.create_web_call(
    organization_id="org_123",
    assistant_id="asst_123",
    futureOption=True,
)
```

## Methods

`create_call` · `create_web_call` · `list_call_logs` · `get_call_log` · `refresh_recording_url` · `list_assistants` · `create_assistant` · `get_assistant` · `update_assistant` · `delete_assistant` · `create_lead` · `get_metrics`

The async client exposes the same methods and parameters.

Assistant create/update can return a successful fallback without an `assistant` object if the write succeeded but the new row could not be read back. Narrow the response before accessing it:

```python
result = client.create_assistant(name="Destek")
if "assistant" in result:
    print(result["assistant"]["id"])
else:
    print(result["warning"])
```

## Errors and retries

Non-2xx responses raise a typed subclass of `OloVoiceError`. Errors expose `.status`, `.body`, `.request_id`, and `.retry_after` (seconds, when the response supplied a valid `Retry-After` header):

```python
from olovoice import PaymentRequiredError, RateLimitError

try:
    client.create_call(...)
except PaymentRequiredError:
    ...  # insufficient wallet balance or plan limit
except RateLimitError as error:
    print(error.retry_after)
```

`400 BadRequestError` · `401 AuthenticationError` · `402 PaymentRequiredError` · `403 PermissionDeniedError` · `404 NotFoundError` · `409 ConflictError` · `429 RateLimitError` · `5xx InternalServerError` · transport `APIConnectionError`.

Successful responses must contain a JSON object. Empty, non-JSON, scalar, and redirect responses raise `InvalidResponseError` with the bounded raw body, HTTP status, and request ID when available.

GET requests retry automatically on 429, 5xx, and network errors (`max_retries=2` by default), honoring `Retry-After` seconds or HTTP dates. Mutating requests are not automatically retried because replaying `/call` can dial twice.

`timeout` is a total deadline for each individual HTTP attempt, covering response headers, the complete bounded response body, and JSON decoding. Retry backoff and a server-provided `Retry-After` wait happen between attempts and do not consume the next attempt's deadline.

The SDK requests identity-encoded responses and rejects compressed response bodies before reading them. This keeps the 2 MiB decoded-body limit enforceable even against compression bombs.

## Base URL safety

The default and canonical origin is `https://api.olovoice.ai`. A different HTTPS origin is allowed only with an explicit opt-in:

```python
client = OloVoice(
    base_url="https://api.staging.example",
    dangerously_allow_custom_base_url=True,
)
```

Plain HTTP additionally requires `dangerously_allow_insecure_http=True` and is restricted to loopback hosts:

```python
client = OloVoice(
    base_url="http://127.0.0.1:8000",
    dangerously_allow_custom_base_url=True,
    dangerously_allow_insecure_http=True,
)
```

Base URLs containing user info, path prefixes, queries, or fragments are rejected. Redirects are never followed, so the SDK does not forward bearer credentials to a redirect target.

## Additional notes

- Use `with OloVoice(...)` or `async with AsyncOloVoice(...)`, or call `close()` when finished.
- The synchronous facade uses a dedicated asynchronous transport internally so slow headers and bodies can be cancelled at the total deadline. Custom transports supplied to `OloVoice` must implement `httpx.AsyncBaseTransport`; `httpx.MockTransport` supports both client styles.
- Ambient HTTP proxy and certificate environment variables are not trusted by the SDK. Use an explicit custom asynchronous transport when proxying is required.
- Forking invalidates and closes every live synchronous client before the process is split, so transport sockets and event-loop descriptors are not inherited. Create new `OloVoice` instances in both the parent and child after `fork()`; either inherited instance fails immediately with a clear error.
- `update_assistant` sends only fields you provide. Explicit `None` clears nullable fields; omitting a field leaves it unchanged.
- `refresh_recording_url` returns signed URLs that expire at `expiresInSeconds`.
- Call-log containers such as `timeline`, `toolRuns`, `structuredOutputs`, `metadata`, and `publicPayload` can be `None`.
