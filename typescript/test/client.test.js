import { inspect } from 'node:util';
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { gzipSync } from 'node:zlib';
import {
  OloVoice,
  OloVoiceError,
  AuthenticationError,
  BadRequestError,
  PaymentRequiredError,
  RateLimitError,
  InternalServerError,
  ConnectionError,
  InvalidResponseError,
  isKnownCarrierResponse,
} from '../dist/esm/index.js';

function mockFetch(handler) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url: String(url), init });
    return handler(String(url), init, calls.length);
  };
  return { fn, calls };
}

function jsonResponse(status, body, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

function textResponse(status, body, headers = {}, statusText = '') {
  return new Response(body, { status, statusText, headers });
}

function erroringBodyResponse(headers = {}, status = 200) {
  const body = new ReadableStream({
    start(controller) {
      controller.error(new Error('body exploded'));
    },
  });
  return new Response(body, { status, headers });
}

function validCallParams() {
  return {
    assistantId: 'a-1',
    phoneNumberId: 'p-1',
    customer: { number: '+905551234567' },
    firstMessage: 'Merhaba',
    content: 'Yardımcı ol.',
    llm: { provider: 'openai', model: 'gpt-4.1-mini' },
    tts: { provider: 'elevenlabs', model: 'eleven_turbo_v2_5', voiceId: 'voice-1' },
    stt: { provider: 'deepgram', model: 'nova-2', language: 'tr' },
    conversation: {},
    backgroundAudio: {},
  };
}

function listen(server) {
  return new Promise((resolve, reject) => {
    const onError = (error) => reject(error);
    server.once('error', onError);
    server.listen(0, '127.0.0.1', () => {
      server.off('error', onError);
      const address = server.address();
      if (!address || typeof address === 'string') {
        reject(new Error('test server did not expose a TCP address'));
        return;
      }
      resolve(address.port);
    });
  });
}

function close(server) {
  return new Promise((resolve, reject) => {
    server.close((error) => (error ? reject(error) : resolve()));
    server.closeAllConnections?.();
  });
}

test('sends protected bearer/JSON headers and hits the right URL', async () => {
  const defaultHeaders = {
    authorization: 'Bearer attacker-controlled',
    'content-type': 'text/plain',
    'AcCePt-EnCoDiNg': 'gzip',
    host: 'attacker.example',
    'x-trace-id': 'trace-before',
  };
  const { fn, calls } = mockFetch(() =>
    jsonResponse(
      200,
      { success: true, payload: { callId: 'c-1' } },
      { 'content-encoding': 'identity' },
    ),
  );
  const client = new OloVoice({ apiKey: 'sk-test', fetch: fn, defaultHeaders });
  defaultHeaders['x-trace-id'] = 'mutated-after-construction';

  const res = await client.calls.create(validCallParams());
  assert.equal(res.payload.callId, 'c-1');
  assert.equal(calls[0].url, 'https://api.olovoice.ai/call');
  assert.equal(calls[0].init.method, 'POST');
  assert.equal(calls[0].init.redirect, 'manual');
  const headers = new Headers(calls[0].init.headers);
  assert.equal(headers.get('authorization'), 'Bearer sk-test');
  assert.equal(headers.get('accept-encoding'), 'identity');
  assert.equal(headers.get('content-type'), 'application/json');
  assert.equal(headers.get('host'), null);
  assert.equal(headers.get('x-trace-id'), 'trace-before');
  assert.equal(JSON.parse(calls[0].init.body).customer.number, '+905551234567');
});

test('does not replay an authenticated POST body across a 307 redirect', async () => {
  let initialRequests = 0;
  let redirectedRequests = 0;
  let redirectedAuthorization;
  let redirectedBody = '';

  const target = createServer((request, response) => {
    redirectedRequests += 1;
    redirectedAuthorization = request.headers.authorization;
    request.setEncoding('utf8');
    request.on('data', (chunk) => {
      redirectedBody += chunk;
    });
    request.on('end', () => {
      response.writeHead(200, { 'content-type': 'application/json' });
      response.end('{"success":true}');
    });
  });
  const targetPort = await listen(target);

  const redirector = createServer((request, response) => {
    initialRequests += 1;
    request.resume();
    response.writeHead(307, { Location: `http://127.0.0.1:${targetPort}/stolen` });
    response.end();
  });
  const redirectorPort = await listen(redirector);

  try {
    const client = new OloVoice({
      apiKey: 'sk-redirect-secret',
      baseUrl: `http://127.0.0.1:${redirectorPort}`,
      dangerouslyAllowCustomBaseUrl: true,
      dangerouslyAllowInsecureHttp: true,
      maxRetries: 0,
    });

    await assert.rejects(client.calls.create(validCallParams()), (err) => {
      assert.ok(err instanceof OloVoiceError);
      assert.ok(!(err instanceof ConnectionError));
      assert.equal(err.status, 307);
      return true;
    });
    assert.equal(initialRequests, 1);
    assert.equal(redirectedRequests, 0);
    assert.equal(redirectedAuthorization, undefined);
    assert.equal(redirectedBody, '');
  } finally {
    await Promise.all([close(redirector), close(target)]);
  }
});

test('builds query strings and encodes path params', async () => {
  const { fn, calls } = mockFetch(() => jsonResponse(200, { data: [], meta: {} }));
  const client = new OloVoice({ apiKey: 'k', fetch: fn });
  await client.callLogs.list({ limit: 50, page: 2 });
  assert.equal(calls[0].url, 'https://api.olovoice.ai/call-logs?limit=50&page=2');

  const pathIds = ['id with space', 'slash/value', '100%', '?query#fragment', 'çağrı'];
  for (const id of pathIds) await client.callLogs.get(id);
  pathIds.forEach((id, index) => {
    assert.equal(
      calls[index + 1].url,
      `https://api.olovoice.ai/call-logs/${encodeURIComponent(id)}`,
    );
  });

  await client.callLogs.list({ limit: undefined, organizationId: 'org/a?x#y &ü' });
  const queryUrl = new URL(calls.at(-1).url);
  assert.equal(queryUrl.searchParams.get('organizationId'), 'org/a?x#y &ü');
  assert.equal(queryUrl.searchParams.has('limit'), false);
});

test('keeps API credentials private and serialization secret-free', () => {
  const client = new OloVoice({ apiKey: 'sk-super-secret', maxRetries: 3 });
  assert.equal(client.apiKey, undefined);
  assert.ok(!Object.keys(client).includes('apiKey'));
  assert.ok(!inspect(client, { showHidden: true }).includes('sk-super-secret'));
  const serialized = JSON.stringify(client);
  assert.ok(!serialized.includes('sk-super-secret'));
  assert.deepEqual(JSON.parse(serialized), {
    baseUrl: 'https://api.olovoice.ai',
    timeoutMs: 30_000,
    maxRetries: 3,
  });
});

test('cannot redirect authenticated requests by mutating the public baseUrl view', async () => {
  const { fn, calls } = mockFetch(() => jsonResponse(200, { ok: true }));
  const client = new OloVoice({ apiKey: 'sk-secret', fetch: fn });

  assert.throws(() => {
    client.baseUrl = 'https://attacker.example';
  }, TypeError);

  // Even deliberate property shadowing cannot change the private request target.
  Object.defineProperty(client, 'baseUrl', { value: 'https://attacker.example' });
  await client.metrics.get();
  assert.equal(calls[0].url, 'https://api.olovoice.ai/metrics');
  assert.equal(JSON.parse(JSON.stringify(client)).baseUrl, 'https://api.olovoice.ai');
});

test('requires explicit opt-ins for custom HTTPS and loopback HTTP base URLs', async () => {
  assert.throws(
    () => new OloVoice({ apiKey: 'k', baseUrl: 'https://staging.example.com' }),
    /dangerouslyAllowCustomBaseUrl/,
  );

  const custom = mockFetch(() => jsonResponse(200, { ok: true }));
  const customClient = new OloVoice({
    apiKey: 'k',
    baseUrl: 'https://staging.example.com/',
    dangerouslyAllowCustomBaseUrl: true,
    fetch: custom.fn,
  });
  await customClient.metrics.get();
  assert.equal(custom.calls[0].url, 'https://staging.example.com/metrics');

  assert.throws(
    () =>
      new OloVoice({
        apiKey: 'k',
        baseUrl: 'http://127.0.0.1:8787',
        dangerouslyAllowCustomBaseUrl: true,
      }),
    /dangerouslyAllowInsecureHttp/,
  );
  const loopback = new OloVoice({
    apiKey: 'k',
    baseUrl: 'http://localhost:8787',
    dangerouslyAllowCustomBaseUrl: true,
    dangerouslyAllowInsecureHttp: true,
  });
  assert.equal(loopback.baseUrl, 'http://localhost:8787');

  for (const baseUrl of [
    'http://example.com',
    'http://localhost.evil.example',
    'http://dev.localhost',
  ]) {
    assert.throws(
      () =>
        new OloVoice({
          apiKey: 'k',
          baseUrl,
          dangerouslyAllowCustomBaseUrl: true,
          dangerouslyAllowInsecureHttp: true,
        }),
      /loopback/,
    );
  }
});

test('rejects base URL userinfo, path prefixes, query strings, fragments, and other schemes', () => {
  const cases = [
    'https://user:pass@api.olovoice.ai',
    'https://api.olovoice.ai/api/v1',
    'https://api.olovoice.ai?tenant=x',
    'https://api.olovoice.ai#fragment',
    'ftp://api.olovoice.ai',
  ];
  for (const baseUrl of cases) {
    assert.throws(() => new OloVoice({ apiKey: 'k', baseUrl }));
  }
});

test('validates API key, timeout, retry, fetch, and dangerous boolean options', () => {
  assert.throws(() => new OloVoice({ apiKey: '   ' }), /missing API key/);
  for (const timeoutMs of [0, -1, Number.NaN, Number.POSITIVE_INFINITY]) {
    assert.throws(() => new OloVoice({ apiKey: 'k', timeoutMs }), /timeoutMs/);
  }
  for (const maxRetries of [-1, 1.5, 11, Number.POSITIVE_INFINITY]) {
    assert.throws(() => new OloVoice({ apiKey: 'k', maxRetries }), /maxRetries/);
  }
  assert.throws(() => new OloVoice({ apiKey: 'k', fetch: null }), /fetch/);
  assert.throws(
    () => new OloVoice({ apiKey: 'k', dangerouslyAllowCustomBaseUrl: 'yes' }),
    /must be a boolean/,
  );
});

test('maps statuses to typed errors with server message and request ID', async () => {
  const cases = [
    [401, { error: 'Unauthorized' }, AuthenticationError],
    [400, { success: false, error: 'customer.number gecersiz' }, BadRequestError],
    [402, { success: false, error: 'Yetersiz bakiye', requestId: 'body-request' }, PaymentRequiredError],
  ];
  for (const [status, body, cls] of cases) {
    const { fn } = mockFetch(() => jsonResponse(status, body));
    const client = new OloVoice({ apiKey: 'k', fetch: fn });
    await assert.rejects(client.calls.create(validCallParams()), (err) => {
      assert.ok(err instanceof cls, `${status} should map to ${cls.name}`);
      assert.equal(err.status, status);
      assert.equal(err.message, body.error);
      if (body.requestId) assert.equal(err.requestId, body.requestId);
      return true;
    });
  }
});

test('retries GET according to Retry-After and never retries POST', async () => {
  let getCount = 0;
  const { fn } = mockFetch(() => {
    getCount += 1;
    return getCount < 2
      ? jsonResponse(429, { error: 'rate limited' }, { 'retry-after': '0.03' })
      : jsonResponse(200, { success: true, assistants: [] });
  });
  const client = new OloVoice({ apiKey: 'k', fetch: fn, maxRetries: 1 });
  const started = Date.now();
  const res = await client.assistants.list();
  assert.equal(res.success, true);
  assert.equal(getCount, 2);
  assert.ok(Date.now() - started >= 20, 'Retry-After delay should be honored');

  let postCount = 0;
  const { fn: postFn } = mockFetch(() => {
    postCount += 1;
    return jsonResponse(429, { error: 'rate limited' }, { 'retry-after': '2' });
  });
  const postClient = new OloVoice({ apiKey: 'k', fetch: postFn, maxRetries: 5 });
  await assert.rejects(postClient.leads.create({ name: 'a', phone: '1' }), (err) => {
    assert.ok(err instanceof RateLimitError);
    assert.equal(err.retryAfterMs, 2_000);
    return true;
  });
  assert.equal(postCount, 1, 'POST must not be retried');
});

test('parses HTTP-date Retry-After values without retrying unsafe requests', async () => {
  const future = new Date(Date.now() + 10_000).toUTCString();
  const { fn } = mockFetch(() =>
    jsonResponse(429, { error: 'later' }, { 'retry-after': future }),
  );
  const client = new OloVoice({ apiKey: 'k', fetch: fn });
  await assert.rejects(client.leads.create({ name: 'a', phone: '1' }), (err) => {
    assert.ok(err instanceof RateLimitError);
    assert.ok(err.retryAfterMs >= 8_000 && err.retryAfterMs <= 10_000);
    return true;
  });
});

test('timeout covers a response body that never finishes', async () => {
  const fn = async () =>
    new Response(
      new ReadableStream({
        start() {
          // Intentionally never close or error the body.
        },
      }),
      { status: 200 },
    );
  const client = new OloVoice({ apiKey: 'k', fetch: fn, timeoutMs: 30, maxRetries: 0 });
  const started = Date.now();
  await assert.rejects(client.metrics.get(), (err) => {
    assert.ok(err instanceof ConnectionError);
    assert.match(err.message, /timed out after 30ms/);
    return true;
  });
  assert.ok(Date.now() - started < 500, 'body timeout should settle promptly');
});

test('retries response-body failures for GET but not POST', async () => {
  let getCount = 0;
  const getFetch = async () => {
    getCount += 1;
    return getCount === 1
      ? erroringBodyResponse({ 'retry-after': '0' })
      : jsonResponse(200, { success: true, assistants: [] });
  };
  const getClient = new OloVoice({ apiKey: 'k', fetch: getFetch, maxRetries: 1 });
  assert.equal((await getClient.assistants.list()).success, true);
  assert.equal(getCount, 2);

  let postCount = 0;
  const postFetch = async () => {
    postCount += 1;
    return erroringBodyResponse();
  };
  const postClient = new OloVoice({ apiKey: 'k', fetch: postFetch, maxRetries: 5 });
  await assert.rejects(postClient.calls.create(validCallParams()), (err) => {
    assert.ok(err instanceof ConnectionError);
    assert.match(err.message, /Response body read failed/);
    return true;
  });
  assert.equal(postCount, 1);
});

test('does not retry 3xx/4xx body failures and preserves the typed HTTP status', async () => {
  let unauthorizedCount = 0;
  const unauthorizedClient = new OloVoice({
    apiKey: 'k',
    maxRetries: 3,
    fetch: async () => {
      unauthorizedCount += 1;
      return unauthorizedCount === 1
        ? erroringBodyResponse({ 'x-request-id': 'req-401' }, 401)
        : jsonResponse(200, { success: true, assistants: [] });
    },
  });
  await assert.rejects(unauthorizedClient.assistants.list(), (err) => {
    assert.ok(err instanceof AuthenticationError);
    assert.ok(!(err instanceof ConnectionError));
    assert.equal(err.status, 401);
    assert.equal(err.requestId, 'req-401');
    return true;
  });
  assert.equal(unauthorizedCount, 1);

  let redirectCount = 0;
  const redirectClient = new OloVoice({
    apiKey: 'k',
    maxRetries: 3,
    fetch: async () => {
      redirectCount += 1;
      return erroringBodyResponse({}, 307);
    },
  });
  await assert.rejects(redirectClient.assistants.list(), (err) => {
    assert.ok(err instanceof OloVoiceError);
    assert.ok(!(err instanceof ConnectionError));
    assert.equal(err.status, 307);
    return true;
  });
  assert.equal(redirectCount, 1);
});

test('retries 5xx body failures and keeps the final error status-typed', async () => {
  let recoveryCount = 0;
  const recoveryClient = new OloVoice({
    apiKey: 'k',
    maxRetries: 1,
    fetch: async () => {
      recoveryCount += 1;
      return recoveryCount === 1
        ? erroringBodyResponse({ 'retry-after': '0' }, 503)
        : jsonResponse(200, { success: true, assistants: [] });
    },
  });
  assert.equal((await recoveryClient.assistants.list()).success, true);
  assert.equal(recoveryCount, 2);

  let finalCount = 0;
  const finalClient = new OloVoice({
    apiKey: 'k',
    maxRetries: 1,
    fetch: async () => {
      finalCount += 1;
      return erroringBodyResponse({ 'retry-after': '0', 'x-request-id': 'req-503' }, 503);
    },
  });
  await assert.rejects(finalClient.assistants.list(), (err) => {
    assert.ok(err instanceof InternalServerError);
    assert.ok(!(err instanceof ConnectionError));
    assert.equal(err.status, 503);
    assert.equal(err.requestId, 'req-503');
    return true;
  });
  assert.equal(finalCount, 2);
});

test('keeps 200 body timeouts retryable for GET requests', async () => {
  let count = 0;
  const client = new OloVoice({
    apiKey: 'k',
    timeoutMs: 25,
    maxRetries: 1,
    fetch: async () => {
      count += 1;
      if (count > 1) return jsonResponse(200, { success: true, assistants: [] });
      return new Response(
        new ReadableStream({
          start() {
            // Retry-After keeps this regression fast while the body times out.
          },
        }),
        { status: 200, headers: { 'retry-after': '0' } },
      );
    },
  });
  assert.equal((await client.assistants.list()).success, true);
  assert.equal(count, 2);
});

test('keeps 200 response parsing timeouts retryable for GET requests', async () => {
  const originalParse = JSON.parse;
  let delayed = false;
  let count = 0;

  JSON.parse = function parseWithOneDelay(text, reviver) {
    if (!delayed && typeof text === 'string' && text.includes('"slowParse":true')) {
      delayed = true;
      const deadline = Date.now() + 75;
      while (Date.now() < deadline) {
        // Simulate a synchronous parse that crosses the per-request deadline.
      }
    }
    return originalParse.call(JSON, text, reviver);
  };

  try {
    const client = new OloVoice({
      apiKey: 'k',
      timeoutMs: 50,
      maxRetries: 1,
      fetch: async () => {
        count += 1;
        return count === 1
          ? jsonResponse(200, { slowParse: true }, { 'retry-after': '0' })
          : jsonResponse(200, { success: true, assistants: [] });
      },
    });
    assert.equal((await client.assistants.list()).success, true);
    assert.equal(delayed, true, 'the first response must exercise the parsing deadline');
    assert.equal(count, 2);
  } finally {
    JSON.parse = originalParse;
  }
});

test('treats a response without an HTTP status as a retryable transport failure', async () => {
  let count = 0;
  const client = new OloVoice({
    apiKey: 'k',
    maxRetries: 1,
    fetch: async () => {
      count += 1;
      return count === 1
        ? Response.error()
        : jsonResponse(200, { success: true, assistants: [] });
    },
  });
  assert.equal((await client.assistants.list()).success, true);
  assert.equal(count, 2);
});

test('rejects empty, non-JSON, and non-object successful responses', async () => {
  const cases = [
    [new Response(null, { status: 204, headers: { 'x-request-id': 'empty-id' } }), '', 'empty-id'],
    [
      textResponse(200, `not-json-${'x'.repeat(2_000)}`, { 'x-request-id': 'text-id' }),
      null,
      'text-id',
    ],
    [jsonResponse(200, ['unexpected-array']), '["unexpected-array"]', undefined],
  ];
  for (const [response, expectedBody, expectedRequestId] of cases) {
    const client = new OloVoice({ apiKey: 'k', fetch: async () => response, maxRetries: 0 });
    await assert.rejects(client.assistants.list(), (err) => {
      assert.ok(err instanceof InvalidResponseError);
      assert.equal(err.status, response.status);
      assert.ok(typeof err.body === 'string');
      assert.ok(err.body.length <= 1_024);
      if (expectedBody !== null) assert.equal(err.body, expectedBody);
      assert.equal(err.requestId, expectedRequestId);
      return true;
    });
  }
});

test('rejects response bodies above 2 MiB using both declared and measured bytes', async () => {
  const limit = 2 * 1_024 * 1_024;
  const declaredTooLarge = new Response('{"ok":true}', {
    status: 200,
    headers: {
      'content-length': String(limit + 1),
      'x-request-id': 'declared-large',
    },
  });
  const declaredClient = new OloVoice({
    apiKey: 'k',
    fetch: async () => declaredTooLarge,
    maxRetries: 0,
  });
  await assert.rejects(declaredClient.metrics.get(), (err) => {
    assert.ok(err instanceof InvalidResponseError);
    assert.equal(err.status, 200);
    assert.equal(err.requestId, 'declared-large');
    assert.match(err.message, /2097152 bytes/);
    return true;
  });

  let pull = 0;
  const lyingStream = new ReadableStream({
    pull(controller) {
      if (pull === 0) controller.enqueue(new Uint8Array(limit));
      else if (pull === 1) controller.enqueue(Uint8Array.of(0));
      else controller.close();
      pull += 1;
    },
  });
  const measuredClient = new OloVoice({
    apiKey: 'k',
    fetch: async () =>
      new Response(lyingStream, {
        status: 200,
        headers: { 'content-length': '1', 'x-request-id': 'measured-large' },
      }),
    maxRetries: 0,
  });
  await assert.rejects(measuredClient.metrics.get(), (err) => {
    assert.ok(err instanceof InvalidResponseError);
    assert.equal(err.status, 200);
    assert.equal(err.requestId, 'measured-large');
    return true;
  });
});

test('requests identity encoding and rejects gzip before reading an expanded body', async () => {
  const expanded = Buffer.from(JSON.stringify({ data: 'A'.repeat(3 * 1_024 * 1_024) }));
  const compressed = gzipSync(expanded);
  assert.ok(compressed.byteLength < 2 * 1_024 * 1_024);

  let requestEncoding;
  const server = createServer((request, response) => {
    requestEncoding = request.headers['accept-encoding'];
    request.resume();
    response.writeHead(200, {
      'content-type': 'application/json',
      'content-encoding': 'gzip',
      'content-length': String(compressed.byteLength),
      'x-request-id': 'gzip-bomb',
    });
    response.end(compressed);
  });
  const port = await listen(server);

  try {
    const client = new OloVoice({
      apiKey: 'k',
      baseUrl: `http://127.0.0.1:${port}`,
      dangerouslyAllowCustomBaseUrl: true,
      dangerouslyAllowInsecureHttp: true,
      maxRetries: 0,
    });
    await assert.rejects(client.metrics.get(), (err) => {
      assert.ok(err instanceof InvalidResponseError);
      assert.equal(err.status, 200);
      assert.equal(err.requestId, 'gzip-bomb');
      assert.match(err.message, /Content-Encoding `gzip`/);
      return true;
    });
    assert.equal(requestEncoding, 'identity');
  } finally {
    await close(server);
  }
});

test('applies status-aware retries to compressed and oversized 429/5xx bodies', async () => {
  let compressedCount = 0;
  const compressedClient = new OloVoice({
    apiKey: 'k',
    maxRetries: 1,
    fetch: async () => {
      compressedCount += 1;
      return compressedCount === 1
        ? new Response('compressed-placeholder', {
            status: 429,
            headers: { 'content-encoding': 'gzip', 'retry-after': '0.02' },
          })
        : jsonResponse(200, { success: true, assistants: [] });
    },
  });
  const started = Date.now();
  assert.equal((await compressedClient.assistants.list()).success, true);
  assert.equal(compressedCount, 2);
  assert.ok(Date.now() - started >= 15, 'compressed 429 should honor Retry-After');

  const finalCompressedClient = new OloVoice({
    apiKey: 'k',
    maxRetries: 0,
    fetch: async () =>
      new Response('compressed-placeholder', {
        status: 429,
        headers: {
          'content-encoding': 'gzip',
          'retry-after': '2',
          'x-request-id': 'compressed-429',
        },
      }),
  });
  await assert.rejects(finalCompressedClient.assistants.list(), (err) => {
    assert.ok(err instanceof RateLimitError);
    assert.equal(err.status, 429);
    assert.equal(err.retryAfterMs, 2_000);
    assert.equal(err.requestId, 'compressed-429');
    return true;
  });

  let oversizedCount = 0;
  const oversizedStarted = Date.now();
  const oversizedClient = new OloVoice({
    apiKey: 'k',
    maxRetries: 1,
    fetch: async () => {
      oversizedCount += 1;
      return new Response('small-wire-body', {
        status: 503,
        headers: {
          'content-length': String(2 * 1_024 * 1_024 + 1),
          'retry-after': '0.02',
          'x-request-id': 'oversized-503',
        },
      });
    },
  });
  await assert.rejects(oversizedClient.assistants.list(), (err) => {
    assert.ok(err instanceof InternalServerError);
    assert.equal(err.status, 503);
    assert.equal(err.requestId, 'oversized-503');
    return true;
  });
  assert.equal(oversizedCount, 2);
  assert.ok(Date.now() - oversizedStarted >= 15, 'oversized 5xx should honor Retry-After');
});

test('returns useful bounded text for non-JSON HTTP errors', async () => {
  const raw = `upstream meltdown ${'x'.repeat(2_000)}`;
  const { fn } = mockFetch(() =>
    textResponse(502, raw, { 'x-request-id': 'req-502' }, 'Bad Gateway'),
  );
  const client = new OloVoice({ apiKey: 'k', fetch: fn, maxRetries: 0 });
  await assert.rejects(client.assistants.list(), (err) => {
    assert.ok(err instanceof InternalServerError);
    assert.equal(err.status, 502);
    assert.equal(err.requestId, 'req-502');
    assert.match(err.message, /^HTTP 502 Bad Gateway: upstream meltdown/);
    assert.equal(err.body.length, 1_024);
    assert.ok(err.message.length <= 1_050);
    return true;
  });
});

test('accepts normal, duplicate, and skipped carrier result objects', async () => {
  const variants = [
    { ok: true },
    { ok: true, duplicate: true, reason: 'request_replay', requestId: null, callId: null },
    {
      ok: true,
      skipped: true,
      status: 'completed',
      reason: 'same_number_parallel_blocked',
      activeCallId: null,
      activeStatus: null,
    },
  ];
  for (const carrier of variants) {
    assert.equal(isKnownCarrierResponse(carrier), true);
    const client = new OloVoice({
      apiKey: 'k',
      fetch: async () =>
        jsonResponse(200, {
          success: true,
          subscriptionLimits: {},
          payload: { callId: 'c-1' },
          carrier,
        }),
    });
    assert.deepEqual((await client.calls.create(validCallParams())).carrier, carrier);
  }

  for (const carrier of ['raw upstream text', null, ['unexpected'], 42, { custom: true }]) {
    assert.equal(isKnownCarrierResponse(carrier), false);
    const client = new OloVoice({
      apiKey: 'k',
      fetch: async () =>
        jsonResponse(200, {
          success: true,
          subscriptionLimits: {},
          payload: { callId: 'c-1' },
          carrier,
        }),
    });
    assert.deepEqual((await client.calls.create(validCallParams())).carrier, carrier);
  }
});

test('accepts object success bodies including assistant delete', async () => {
  const client = new OloVoice({ apiKey: 'k', fetch: async () => jsonResponse(200, { success: true }) });
  assert.deepEqual(await client.assistants.delete('assistant-1'), { success: true });
});

test('requires an API key without permanently mutating the process environment', () => {
  const previous = process.env.OLOVOICE_API_KEY;
  try {
    delete process.env.OLOVOICE_API_KEY;
    assert.throws(() => new OloVoice(), /missing API key/);
  } finally {
    if (previous === undefined) delete process.env.OLOVOICE_API_KEY;
    else process.env.OLOVOICE_API_KEY = previous;
  }
});
