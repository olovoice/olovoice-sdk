# OloVoice — TypeScript/JavaScript SDK

Official SDK for the [OloVoice Public API](https://docs.olovoice.ai). Zero dependencies, fully typed, and requires Node 22+ with its built-in `fetch`.

## Install

```bash
npm install olovoice@0.1.0
```

This SDK is a public beta. Interfaces may evolve before 1.0, so pin and test an
exact SDK version for production use.

## Quick start

```ts
import { OloVoice, isKnownCarrierResponse } from 'olovoice';

const client = new OloVoice({ apiKey: process.env.OLOVOICE_API_KEY });

// A direct assistant call carries the complete runtime configuration.
const call = await client.calls.create({
  assistantId: 'YOUR_ASSISTANT_ID',
  phoneNumberId: 'YOUR_PHONE_NUMBER_ID',
  customer: { number: '+905551234567', name: 'Kemal' },
  firstMessage: 'Merhaba Kemal, size nasıl yardımcı olabilirim?',
  content: 'Kısa ve doğru yanıt veren bir müşteri destek asistanısın.',
  llm: { provider: 'openai', model: 'gpt-4.1-mini' },
  tts: {
    provider: 'elevenlabs',
    model: 'eleven_turbo_v2_5',
    voiceId: 'YOUR_VOICE_ID',
  },
  stt: { provider: 'deepgram', model: 'nova-2', language: 'tr' },
  conversation: {},
  backgroundAudio: {},
});

console.log(call.payload.callId);
if (isKnownCarrierResponse(call.carrier) && call.carrier.skipped) {
  console.log('Carrier skipped the dial:', call.carrier.reason);
}

const log = await client.callLogs.get(call.payload.callId);
console.log(log.data.status, log.data.analysisSummary);
```

The SDK sends requests to `https://api.olovoice.ai` without adding `/api/v1` or `/api/public`. Request fields are camelCase; the API rejects snake_case fields with `400`.

## Outbound configuration rules

`calls.create` requires at least one of `assistantId`, `squadId`, or `workflowId`. Multiple selectors are accepted by the API.

- A plain `assistantId` call must include `firstMessage` and `content`. A squad or workflow may hydrate those fields instead.
- `llm`, `conversation`, and `backgroundAudio` are always required.
- A classic LLM pipeline requires both `tts` and `stt`.
- A recognized OpenAI realtime provider/model defaults to `halfCascade`: `tts` is required and `stt` may be omitted.
- `nativeAudio` must be explicit on a recognized realtime provider/model; both `tts` and `stt` may then be omitted.
- `privacy` and `predefinedFunctions` may be omitted; the API defaults them to empty objects.

Call-time STT overrides may be partial because the worker merges them with stored assistant settings. Call-time `keywords` and background-audio channels also accept runtime string shorthands. Assistant create/update inputs are deliberately stricter: an STT config needs a provider, keyword entries use `{ phrase, boost }`, and `backgroundAudio.thinking` uses `{ builtin, volume }` so values are not silently discarded by assistant storage.

## Web calls (browser/WebRTC)

`calls.createWeb` returns short-lived browser session credentials. Call it from your backend—never expose an API key in browser code—then pass only `token` and `connectionUrl` to your frontend WebRTC client.

```ts
const web = await client.calls.createWeb({
  organizationId: 'YOUR_ORG_ID',
  assistantId: 'YOUR_ASSISTANT_ID',
});
```

Web calls can hydrate a stored assistant, so this minimal form is valid. If you provide overrides, LLM needs `provider` and `model`. TTS is provider-specific: AWS needs `voiceId` but defaults its model; Freya/Nova can use provider-only defaults; ElevenLabs/OpenAI require both `model` and `voiceId`.

## Resources

| Resource | Methods |
| --- | --- |
| `client.calls` | `create`, `createWeb` |
| `client.callLogs` | `list`, `get`, `refreshRecordingUrl` |
| `client.assistants` | `list`, `create`, `get`, `update`, `delete` |
| `client.leads` | `create` |
| `client.metrics` | `get` |

## Error handling

Non-2xx responses throw a typed `OloVoiceError` subclass with `status`, `body`, `requestId`, and—when supplied by the server—`retryAfterMs`. Empty, malformed, non-object, or oversized responses throw `InvalidResponseError` instead of being returned as a typed success value. Response bodies are stream-limited to 2 MiB before JSON parsing.

```ts
import {
  InvalidResponseError,
  PaymentRequiredError,
  RateLimitError,
} from 'olovoice';

try {
  await client.assistants.list();
} catch (err) {
  if (err instanceof RateLimitError) {
    console.error('Retry after (ms):', err.retryAfterMs);
  } else if (err instanceof PaymentRequiredError) {
    console.error('Insufficient wallet balance');
  } else if (err instanceof InvalidResponseError) {
    console.error('Unexpected upstream response:', err.status, err.requestId);
  } else {
    throw err;
  }
}
```

`400 BadRequestError` · `401 AuthenticationError` · `402 PaymentRequiredError` · `403 PermissionDeniedError` · `404 NotFoundError` · `409 ConflictError` · `429 RateLimitError` · `5xx InternalServerError` · network/body-read/timeout `ConnectionError`.

GET requests retry network/no-status failures, 2xx body-read/parsing timeouts, `429`, and `5xx` responses. Unreadable, compressed, or oversized `429`/`5xx` bodies retain their typed HTTP status and follow the same retry policy. Known `3xx`/`4xx` responses other than `429` are never retried, and redirects are never followed. The SDK honors `Retry-After` and otherwise uses exponential backoff. Mutating requests are never retried automatically, avoiding duplicate calls or writes.

## Options and custom origins

```ts
new OloVoice({
  apiKey: '…',             // or OLOVOICE_API_KEY
  timeoutMs: 30_000,       // includes response body consumption
  maxRetries: 2,           // GET-only, integer from 0 to 10
  defaultHeaders: {},
});
```

Credentials go to the canonical HTTPS origin by default. A different HTTPS origin requires an explicit high-risk opt-in:

```ts
new OloVoice({
  apiKey: '…',
  baseUrl: 'https://staging-api.example.com',
  dangerouslyAllowCustomBaseUrl: true,
});
```

Plain HTTP additionally requires `dangerouslyAllowInsecureHttp: true` and is restricted to literal loopback hosts such as `localhost`, `127.0.0.1`, or `::1`. Base URLs containing credentials, a path prefix, query string, or fragment are rejected.

The API key is held in an ECMAScript private field and omitted from object/JSON serialization. SDK-owned authorization/content headers cannot be overridden through differently-cased `defaultHeaders` keys. On Node, the SDK requests `Accept-Encoding: identity` and rejects any response declaring a non-identity `Content-Encoding` before reading its body, preventing transparent decompression from bypassing the 2 MiB decoded-body limit. Browsers may forbid setting `Accept-Encoding`; the response-side rejection still applies when that header is exposed, but this API-key SDK should run on your backend.

## Response nuances

- Carrier bodies are forwarded from the dialer and can be raw text or any JSON value. Use `isKnownCarrierResponse(call.carrier)` before narrowing the ergonomic accepted/duplicate/skipped union. Normal acceptance can be only `{ ok: true }`; do not assume `carrier.callId` exists.
- Assistant create/update can return a warning fallback when post-write readback fails; narrow the response with `'assistant' in response` before reading it.
- Call-log detail containers such as `timeline`, `toolRuns`, `structuredOutputs`, `metadata`, and `publicPayload` can be `null`. Raw internal `payload` is always `null` on public list/detail endpoints.
- `assistants.update` replaces nested config objects wholesale; only `privacy.ologuardEnabled` is preserved when omitted.
- Send `null` in `assistants.update` to clear `firstMessage`, `content`, or `serverUrl`.
- `callLogs.refreshRecordingUrl` returns signed URLs that expire after `expiresInSeconds`.

Full field reference: [docs.olovoice.ai](https://docs.olovoice.ai)
