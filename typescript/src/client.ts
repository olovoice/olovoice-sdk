import { ConnectionError, InvalidResponseError, errorFromStatus } from './errors.js';
import type {
  AssistantResponse,
  CreateAssistantParams,
  CreateAssistantResponse,
  CreateCallParams,
  CreateCallResponse,
  CreateLeadParams,
  CreateLeadResponse,
  CreateWebCallParams,
  CreateWebCallResponse,
  DeleteAssistantResponse,
  GetCallLogResponse,
  GetMetricsParams,
  ListAssistantsParams,
  ListAssistantsResponse,
  ListCallLogsParams,
  ListCallLogsResponse,
  MetricsResponse,
  RecordingUrlResponse,
  UpdateAssistantParams,
  UpdateAssistantResponse,
} from './types.js';

export interface OloVoiceOptions {
  /** API key. Falls back to the OLOVOICE_API_KEY environment variable. */
  apiKey?: string;
  /** Defaults to the canonical https://api.olovoice.ai origin. */
  baseUrl?: string;
  /** Required before sending credentials to a non-canonical HTTPS origin. */
  dangerouslyAllowCustomBaseUrl?: boolean;
  /**
   * Required in addition to `dangerouslyAllowCustomBaseUrl` for loopback HTTP.
   * Non-loopback HTTP is never allowed.
   */
  dangerouslyAllowInsecureHttp?: boolean;
  /** Per-request timeout in milliseconds, including response body reads. Default 30000. */
  timeoutMs?: number;
  /** Retries for GET requests on 429/5xx/network errors. Default 2, maximum 10. */
  maxRetries?: number;
  /** Extra headers sent with every request. SDK-owned and unsafe headers are ignored. */
  defaultHeaders?: Record<string, string>;
  /** Custom fetch implementation (for testing or polyfills). */
  fetch?: typeof globalThis.fetch;
}

type Query = Record<string, string | number | undefined>;
type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';

const VERSION = '0.1.0';
const CANONICAL_BASE_URL = 'https://api.olovoice.ai';
const MAX_RETRIES = 10;
const MAX_RAW_BODY_CHARS = 1_024;
const MAX_ERROR_MESSAGE_CHARS = 1_024;
const MAX_RESPONSE_BODY_BYTES = 2 * 1_024 * 1_024;
const MAX_RETRY_AFTER_MS = 300_000;
const SDK_OWNED_OR_UNSAFE_HEADERS = [
  'accept',
  'accept-encoding',
  'authorization',
  'connection',
  'content-length',
  'content-type',
  'cookie',
  'host',
  'proxy-authorization',
  'set-cookie',
  'transfer-encoding',
  'user-agent',
] as const;

class RequestTimeoutError extends Error {}
class ResponseBodyTooLargeError extends Error {}
class UnsupportedContentEncodingError extends Error {
  constructor(readonly encoding: string) {
    super(`Unsupported response Content-Encoding: ${encoding}`);
  }
}

export class OloVoice {
  readonly #apiKey: string;
  readonly #baseUrl: string;
  readonly #timeoutMs: number;
  readonly #maxRetries: number;
  readonly #defaultHeaders: Headers;
  readonly #fetchImpl: typeof globalThis.fetch;

  constructor(options: OloVoiceOptions = {}) {
    validateBooleanOption('dangerouslyAllowCustomBaseUrl', options.dangerouslyAllowCustomBaseUrl);
    validateBooleanOption('dangerouslyAllowInsecureHttp', options.dangerouslyAllowInsecureHttp);

    const env = (globalThis as { process?: { env?: Record<string, string | undefined> } }).process
      ?.env;
    const rawApiKey = options.apiKey ?? env?.OLOVOICE_API_KEY;
    if (typeof rawApiKey !== 'string' || rawApiKey.trim().length === 0) {
      throw new TypeError(
        'olovoice: missing API key. Pass `apiKey` or set the OLOVOICE_API_KEY environment variable.',
      );
    }

    const timeoutMs = options.timeoutMs ?? 30_000;
    if (!Number.isFinite(timeoutMs) || timeoutMs <= 0) {
      throw new TypeError('olovoice: `timeoutMs` must be a finite number greater than 0.');
    }

    const maxRetries = options.maxRetries ?? 2;
    if (!Number.isInteger(maxRetries) || maxRetries < 0 || maxRetries > MAX_RETRIES) {
      throw new TypeError(
        `olovoice: \`maxRetries\` must be an integer between 0 and ${MAX_RETRIES}.`,
      );
    }

    const fetchImpl = options.fetch === undefined ? globalThis.fetch : options.fetch;
    if (typeof fetchImpl !== 'function') {
      throw new TypeError('olovoice: global fetch is not available. Use Node 22+ or pass `fetch`.');
    }

    const defaultHeaders = new Headers(options.defaultHeaders);
    for (const name of SDK_OWNED_OR_UNSAFE_HEADERS) defaultHeaders.delete(name);

    this.#apiKey = rawApiKey.trim();
    this.#baseUrl = normalizeBaseUrl(options);
    this.#timeoutMs = timeoutMs;
    this.#maxRetries = maxRetries;
    this.#defaultHeaders = defaultHeaders;
    this.#fetchImpl = fetchImpl;
  }

  /** Validated API origin. The private backing value cannot be redirected at runtime. */
  get baseUrl(): string {
    return this.#baseUrl;
  }

  /** A deliberately secret-free representation for JSON/log serializers. */
  toJSON(): { baseUrl: string; timeoutMs: number; maxRetries: number } {
    return {
      baseUrl: this.#baseUrl,
      timeoutMs: this.#timeoutMs,
      maxRetries: this.#maxRetries,
    };
  }

  // -- Calls ---------------------------------------------------------------

  readonly calls = {
    /** Start an outbound phone call. */
    create: (params: CreateCallParams): Promise<CreateCallResponse> =>
      this.#request('POST', '/call', { body: params }),
    /** Create a browser (WebRTC) call; returns a short-lived session token and connection URL. */
    createWeb: (params: CreateWebCallParams): Promise<CreateWebCallResponse> =>
      this.#request('POST', '/web-call', { body: params }),
  };

  // -- Call logs -----------------------------------------------------------

  readonly callLogs = {
    list: (params: ListCallLogsParams = {}): Promise<ListCallLogsResponse> =>
      this.#request('GET', '/call-logs', { query: { ...params } }),
    get: (callId: string, params: { organizationId?: string } = {}): Promise<GetCallLogResponse> =>
      this.#request('GET', `/call-logs/${encodeURIComponent(callId)}`, { query: { ...params } }),
    /** Get fresh short-lived signed recording URLs for a call. */
    refreshRecordingUrl: (
      callId: string,
      params: { organizationId?: string } = {},
    ): Promise<RecordingUrlResponse> =>
      this.#request('GET', `/call-logs/${encodeURIComponent(callId)}/recording-url`, {
        query: { ...params },
      }),
  };

  // -- Assistants ----------------------------------------------------------

  readonly assistants = {
    list: (params: ListAssistantsParams = {}): Promise<ListAssistantsResponse> =>
      this.#request('GET', '/assistants', { query: { ...params } }),
    create: (params: CreateAssistantParams): Promise<CreateAssistantResponse> =>
      this.#request('POST', '/assistants', { body: params }),
    get: (assistantId: string): Promise<AssistantResponse> =>
      this.#request('GET', `/assistants/${encodeURIComponent(assistantId)}`),
    /**
     * Partial update. Nested config objects are fully replaced (not deep-merged),
     * except `privacy.ologuardEnabled`, which is preserved when omitted.
     */
    update: (assistantId: string, params: UpdateAssistantParams): Promise<UpdateAssistantResponse> =>
      this.#request('PATCH', `/assistants/${encodeURIComponent(assistantId)}`, { body: params }),
    delete: (assistantId: string): Promise<DeleteAssistantResponse> =>
      this.#request('DELETE', `/assistants/${encodeURIComponent(assistantId)}`),
  };

  // -- Leads ---------------------------------------------------------------

  readonly leads = {
    create: (params: CreateLeadParams): Promise<CreateLeadResponse> =>
      this.#request('POST', '/leads', { body: params }),
  };

  // -- Metrics -------------------------------------------------------------

  readonly metrics = {
    get: (params: GetMetricsParams = {}): Promise<MetricsResponse> =>
      this.#request('GET', '/metrics', { query: { ...params } }),
  };

  // -- Transport -----------------------------------------------------------

  async #request<T>(
    method: HttpMethod,
    path: string,
    opts: { query?: Query; body?: unknown } = {},
  ): Promise<T> {
    const url = new URL(path, `${this.#baseUrl}/`);
    for (const [key, value] of Object.entries(opts.query ?? {})) {
      if (value !== undefined) url.searchParams.set(key, String(value));
    }

    const headers = new Headers(this.#defaultHeaders);
    headers.set('Authorization', `Bearer ${this.#apiKey}`);
    headers.set('Accept', 'application/json');
    headers.set('User-Agent', `olovoice-node/${VERSION}`);
    // Node fetch otherwise advertises transparent gzip/br decompression. A
    // browser may treat this as a forbidden request header, so response-side
    // Content-Encoding validation below remains the enforcement boundary.
    if (isNodeRuntime()) headers.set('Accept-Encoding', 'identity');

    // Never let fetch replay an authenticated request to a Location target.
    // Manual mode also preserves the 3xx status for a typed SDK error.
    const init: RequestInit = { method, headers, redirect: 'manual' };
    if (opts.body !== undefined) {
      headers.set('Content-Type', 'application/json');
      init.body = JSON.stringify(opts.body);
    }

    // Only GETs are safe to retry: a retried POST /call could dial twice.
    const attempts = method === 'GET' ? this.#maxRetries + 1 : 1;
    let lastError: unknown;
    let retryDelayMs = 0;

    for (let attempt = 0; attempt < attempts; attempt++) {
      if (attempt > 0 && retryDelayMs > 0) await sleep(retryDelayMs);

      const attemptStartedAt = Date.now();
      const controller = new AbortController();
      let timer: ReturnType<typeof setTimeout> | undefined;
      const timeout = new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => {
          controller.abort();
          reject(new RequestTimeoutError());
        }, this.#timeoutMs);
      });

      let response: Response | undefined;
      let requestId: string | undefined;
      let retryAfterMs: number | undefined;
      let text: string;

      try {
        response = await Promise.race([
          this.#fetchImpl(url, { ...init, signal: controller.signal }),
          timeout,
        ]);
        requestId = response.headers.get('x-request-id') ?? undefined;
        retryAfterMs = parseRetryAfter(response.headers.get('retry-after'));
        const unsupportedEncoding = getUnsupportedContentEncoding(
          response.headers.get('content-encoding'),
        );
        if (unsupportedEncoding) {
          void response.body?.cancel().catch(() => undefined);
          throw new UnsupportedContentEncodingError(unsupportedEncoding);
        }
        text = await Promise.race([readResponseText(response, controller.signal), timeout]);
      } catch (cause) {
        // Once an HTTP error status is known, body/encoding failures must not
        // erase it. Non-retryable statuses remain typed; 429/5xx GETs retry.
        if (response && response.status >= 300) {
          lastError = errorFromStatus(
            response.status,
            buildUnreadableHttpErrorMessage(response, cause, this.#timeoutMs),
            undefined,
            requestId,
            retryAfterMs,
          );
          if (!isRetryableStatus(response.status)) break;
          retryDelayMs = retryAfterMs ?? exponentialDelay(attempt);
          continue;
        }
        if (cause instanceof UnsupportedContentEncodingError) {
          throw new InvalidResponseError(
            `Invalid API response: compressed Content-Encoding \`${cause.encoding}\` is not accepted.`,
            { status: response?.status, requestId },
          );
        }
        if (cause instanceof ResponseBodyTooLargeError) {
          throw new InvalidResponseError(
            `Invalid API response: response body exceeded ${MAX_RESPONSE_BODY_BYTES} bytes.`,
            { status: response?.status, requestId },
          );
        }
        const timedOut = cause instanceof RequestTimeoutError || controller.signal.aborted;
        lastError = new ConnectionError(
          timedOut
            ? `Request timed out after ${this.#timeoutMs}ms`
            : response
              ? `Response body read failed: ${formatCause(cause)}`
              : `Request failed: ${formatCause(cause)}`,
          { status: response?.status, requestId, retryAfterMs },
        );
        retryDelayMs = retryAfterMs ?? exponentialDelay(attempt);
        continue;
      } finally {
        if (timer !== undefined) clearTimeout(timer);
      }

      if (response.status === 0) {
        lastError = new ConnectionError('Request failed without an HTTP status.');
        retryDelayMs = exponentialDelay(attempt);
        continue;
      }

      const parsed = parseJson(text);
      if (Date.now() - attemptStartedAt >= this.#timeoutMs) {
        if (response.status >= 300) {
          const statusLabel = `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ''}`;
          lastError = errorFromStatus(
            response.status,
            `${statusLabel}: response parsing timed out after ${this.#timeoutMs}ms`,
            undefined,
            requestId,
            retryAfterMs,
          );
          if (!isRetryableStatus(response.status)) break;
        } else {
          lastError = new ConnectionError(`Request timed out after ${this.#timeoutMs}ms`, {
            status: response.status,
            requestId,
          });
        }
        retryDelayMs = retryAfterMs ?? exponentialDelay(attempt);
        continue;
      }
      if (response.ok) {
        if (!parsed.ok || !isJsonObject(parsed.value)) {
          const reason =
            text.trim().length === 0
              ? 'the response body was empty'
              : parsed.ok
                ? 'the response JSON was not an object'
                : 'the response body was not valid JSON';
          throw new InvalidResponseError(`Invalid API response: ${reason}.`, {
            status: response.status,
            body: boundRawBody(text),
            requestId,
          });
        }
        return parsed.value as T;
      }

      const body = parsed.ok ? parsed.value : boundRawBody(text);
      requestId = requestId ?? getRequestId(body);
      const message = buildHttpErrorMessage(response, parsed.ok ? parsed.value : undefined, text);
      lastError = errorFromStatus(response.status, message, body, requestId, retryAfterMs);

      if (!isRetryableStatus(response.status)) break;
      retryDelayMs = retryAfterMs ?? exponentialDelay(attempt);
    }

    throw lastError ?? new ConnectionError('Request failed before a response was received.');
  }
}

function normalizeBaseUrl(options: OloVoiceOptions): string {
  const raw = options.baseUrl ?? CANONICAL_BASE_URL;
  if (typeof raw !== 'string' || raw.trim().length === 0) {
    throw new TypeError('olovoice: `baseUrl` must be an absolute URL.');
  }

  let parsed: URL;
  try {
    parsed = new URL(raw.trim());
  } catch {
    throw new TypeError('olovoice: `baseUrl` must be an absolute URL.');
  }

  if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
    throw new TypeError('olovoice: `baseUrl` must use HTTPS.');
  }
  if (parsed.username || parsed.password) {
    throw new TypeError('olovoice: `baseUrl` must not contain username or password credentials.');
  }
  if (parsed.search || parsed.hash) {
    throw new TypeError('olovoice: `baseUrl` must not contain a query string or fragment.');
  }
  if (parsed.pathname !== '/') {
    throw new TypeError('olovoice: `baseUrl` must be an origin without a path prefix.');
  }

  const isCanonical = parsed.origin === CANONICAL_BASE_URL;
  if (!isCanonical && options.dangerouslyAllowCustomBaseUrl !== true) {
    throw new TypeError(
      'olovoice: custom `baseUrl` requires `dangerouslyAllowCustomBaseUrl: true`.',
    );
  }

  if (parsed.protocol === 'http:') {
    if (!isLoopbackHost(parsed.hostname)) {
      throw new TypeError('olovoice: insecure HTTP is allowed only for literal loopback hosts.');
    }
    if (options.dangerouslyAllowInsecureHttp !== true) {
      throw new TypeError(
        'olovoice: loopback HTTP requires `dangerouslyAllowInsecureHttp: true`.',
      );
    }
  }

  return parsed.origin;
}

function isLoopbackHost(hostname: string): boolean {
  const normalized = hostname
    .toLowerCase()
    .replace(/^\[|\]$/g, '')
    .replace(/\.$/, '');
  if (normalized === '::1' || normalized === 'localhost') {
    return true;
  }
  return /^127(?:\.\d{1,3}){3}$/.test(normalized);
}

function validateBooleanOption(name: string, value: boolean | undefined): void {
  if (value !== undefined && typeof value !== 'boolean') {
    throw new TypeError(`olovoice: \`${name}\` must be a boolean.`);
  }
}

function isNodeRuntime(): boolean {
  const processValue = (globalThis as { process?: { versions?: { node?: string } } }).process;
  return typeof processValue?.versions?.node === 'string';
}

function getUnsupportedContentEncoding(value: string | null): string | undefined {
  if (value === null) return undefined;
  const encodings = value
    .split(',')
    .map((encoding) => encoding.trim().toLowerCase())
    .filter(Boolean);
  if (encodings.length === 0 || encodings.every((encoding) => encoding === 'identity')) {
    return undefined;
  }
  return value.trim().slice(0, 128);
}

async function readResponseText(response: Response, signal: AbortSignal): Promise<string> {
  const contentLength = response.headers.get('content-length')?.trim();
  if (contentLength && /^\d+$/.test(contentLength)) {
    const declaredBytes = Number(contentLength);
    if (declaredBytes > MAX_RESPONSE_BODY_BYTES) {
      void response.body?.cancel().catch(() => undefined);
      throw new ResponseBodyTooLargeError();
    }
  }

  if (!response.body) return '';

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const chunks: string[] = [];
  let receivedBytes = 0;
  const cancelOnAbort = () => {
    void reader.cancel().catch(() => undefined);
  };

  if (signal.aborted) cancelOnAbort();
  else signal.addEventListener('abort', cancelOnAbort, { once: true });

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (signal.aborted) throw new RequestTimeoutError();
      if (done) break;

      receivedBytes += value.byteLength;
      if (receivedBytes > MAX_RESPONSE_BODY_BYTES) {
        void reader.cancel().catch(() => undefined);
        throw new ResponseBodyTooLargeError();
      }
      chunks.push(decoder.decode(value, { stream: true }));
    }
    chunks.push(decoder.decode());
    return chunks.join('');
  } finally {
    signal.removeEventListener('abort', cancelOnAbort);
    reader.releaseLock();
  }
}

function parseJson(text: string): { ok: true; value: unknown } | { ok: false } {
  if (text.trim().length === 0) return { ok: false };
  try {
    return { ok: true, value: JSON.parse(text) as unknown };
  } catch {
    return { ok: false };
  }
}

function isJsonObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function buildHttpErrorMessage(response: Response, payload: unknown, rawText: string): string {
  const serverMessage = extractServerMessage(payload);
  if (serverMessage) return serverMessage.slice(0, MAX_ERROR_MESSAGE_CHARS);

  const statusLabel = `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ''}`;
  const rawSnippet = rawText.replace(/\s+/g, ' ').trim().slice(0, MAX_ERROR_MESSAGE_CHARS);
  return rawSnippet ? `${statusLabel}: ${rawSnippet}` : statusLabel;
}

function buildUnreadableHttpErrorMessage(
  response: Response,
  cause: unknown,
  timeoutMs: number,
): string {
  const statusLabel = `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ''}`;
  if (cause instanceof UnsupportedContentEncodingError) {
    return `${statusLabel}: compressed Content-Encoding \`${cause.encoding}\` is not accepted`;
  }
  if (cause instanceof ResponseBodyTooLargeError) {
    return `${statusLabel}: response body exceeded ${MAX_RESPONSE_BODY_BYTES} bytes`;
  }
  if (cause instanceof RequestTimeoutError) {
    return `${statusLabel}: response body timed out after ${timeoutMs}ms`;
  }
  return `${statusLabel}: response body read failed: ${formatCause(cause)}`.slice(
    0,
    MAX_ERROR_MESSAGE_CHARS,
  );
}

function extractServerMessage(payload: unknown): string | undefined {
  if (typeof payload === 'string' && payload.trim()) return payload.trim();
  if (!isJsonObject(payload)) return undefined;

  for (const key of ['error', 'message'] as const) {
    const candidate = payload[key];
    if (typeof candidate === 'string' && candidate.trim()) return candidate.trim();
    if (isJsonObject(candidate)) {
      const nested = candidate.message;
      if (typeof nested === 'string' && nested.trim()) return nested.trim();
    }
  }
  return undefined;
}

function getRequestId(payload: unknown): string | undefined {
  if (!isJsonObject(payload)) return undefined;
  const candidate = payload.requestId;
  return typeof candidate === 'string' && candidate.length > 0 ? candidate : undefined;
}

function boundRawBody(text: string): string {
  return text.slice(0, MAX_RAW_BODY_CHARS);
}

function parseRetryAfter(value: string | null): number | undefined {
  if (value === null) return undefined;
  const seconds = Number(value.trim());
  if (Number.isFinite(seconds) && seconds >= 0) {
    return Math.min(Math.ceil(seconds * 1_000), MAX_RETRY_AFTER_MS);
  }

  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return undefined;
  return Math.min(Math.max(0, timestamp - Date.now()), MAX_RETRY_AFTER_MS);
}

function exponentialDelay(attempt: number): number {
  return 500 * 2 ** attempt;
}

function isRetryableStatus(status: number): boolean {
  return status === 429 || status >= 500;
}

function formatCause(cause: unknown): string {
  if (cause instanceof Error && cause.message) return cause.message;
  return String(cause);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
