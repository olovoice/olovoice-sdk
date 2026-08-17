"""Typed errors for the olovoice SDK."""

from __future__ import annotations

from typing import Dict, Optional, Type


class OloVoiceError(Exception):
    """Base error for every non-2xx response or transport failure."""

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        body: object = None,
        request_id: Optional[str] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.request_id = request_id
        self.retry_after = retry_after


class BadRequestError(OloVoiceError):
    """400 — validation error (snake_case keys, bad phone format, missing fields…)."""


class AuthenticationError(OloVoiceError):
    """401 — missing or invalid API key."""


class PaymentRequiredError(OloVoiceError):
    """402 — insufficient wallet balance / plan limit."""


class PermissionDeniedError(OloVoiceError):
    """403 — organizationId mismatch or missing scope."""


class NotFoundError(OloVoiceError):
    """404 — resource not found."""


class ConflictError(OloVoiceError):
    """409 — conflict."""


class RateLimitError(OloVoiceError):
    """429 — rate limited."""


class InternalServerError(OloVoiceError):
    """5xx — server-side failure."""


class APIConnectionError(OloVoiceError):
    """Request never reached the server or timed out."""


class InvalidResponseError(OloVoiceError):
    """The server returned a redirect or a non-object success payload."""


_STATUS_MAP: Dict[int, Type[OloVoiceError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    402: PaymentRequiredError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    429: RateLimitError,
}


def error_from_status(
    status: int,
    message: str,
    body: object,
    request_id: Optional[str] = None,
    retry_after: Optional[float] = None,
) -> OloVoiceError:
    cls = _STATUS_MAP.get(status, InternalServerError if status >= 500 else OloVoiceError)
    return cls(
        message,
        status=status,
        body=body,
        request_id=request_id,
        retry_after=retry_after,
    )
