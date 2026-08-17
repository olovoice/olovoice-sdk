export interface OloVoiceErrorOptions {
  /** HTTP status code, if the server responded. */
  status?: number;
  /** Parsed response body or a bounded raw response body, if any. */
  body?: unknown;
  /** The `x-request-id` / `requestId` when the server provides one. */
  requestId?: string;
  /** Server-requested retry delay parsed from `Retry-After`, in milliseconds. */
  retryAfterMs?: number;
}

/** Base error for every non-2xx response or transport failure. */
export class OloVoiceError extends Error {
  /** HTTP status code, if the server responded. */
  readonly status?: number;
  /** Parsed response body, if any. */
  readonly body?: unknown;
  /** The `x-request-id` / `requestId` when the server provides one. */
  readonly requestId?: string;
  /** Server-requested retry delay parsed from `Retry-After`, in milliseconds. */
  readonly retryAfterMs?: number;

  constructor(message: string, opts: OloVoiceErrorOptions = {}) {
    super(message);
    this.name = new.target.name;
    this.status = opts.status;
    this.body = opts.body;
    this.requestId = opts.requestId;
    this.retryAfterMs = opts.retryAfterMs;
  }
}

/** 400 — validation error (snake_case keys, bad phone format, missing fields…). */
export class BadRequestError extends OloVoiceError {}
/** 401 — missing or invalid API key. */
export class AuthenticationError extends OloVoiceError {}
/** 402 — insufficient wallet balance / plan limit. */
export class PaymentRequiredError extends OloVoiceError {}
/** 403 — organizationId mismatch or missing scope. */
export class PermissionDeniedError extends OloVoiceError {}
/** 404 — resource not found. */
export class NotFoundError extends OloVoiceError {}
/** 409 — conflict (e.g. concurrent update). */
export class ConflictError extends OloVoiceError {}
/** 429 — rate limited. */
export class RateLimitError extends OloVoiceError {}
/** 5xx — server-side failure. */
export class InternalServerError extends OloVoiceError {}
/** Request never reached the server or timed out. */
export class ConnectionError extends OloVoiceError {}
/** A response that could not safely provide the JSON object promised by the API. */
export class InvalidResponseError extends OloVoiceError {}

export function errorFromStatus(
  status: number,
  message: string,
  body: unknown,
  requestId?: string,
  retryAfterMs?: number,
): OloVoiceError {
  const opts = { status, body, requestId, retryAfterMs };
  if (status === 400) return new BadRequestError(message, opts);
  if (status === 401) return new AuthenticationError(message, opts);
  if (status === 402) return new PaymentRequiredError(message, opts);
  if (status === 403) return new PermissionDeniedError(message, opts);
  if (status === 404) return new NotFoundError(message, opts);
  if (status === 409) return new ConflictError(message, opts);
  if (status === 429) return new RateLimitError(message, opts);
  if (status >= 500) return new InternalServerError(message, opts);
  return new OloVoiceError(message, opts);
}
