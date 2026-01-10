from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx


class ApiError(Exception):
    """Base for every error this library raises from an HTTP response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response: httpx.Response | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response


class ClientError(ApiError):
    """A 4xx that isn't one of the more specific cases below."""


class AuthError(ClientError):
    """401 or 403."""


class NotFoundError(ClientError):
    """404."""


class RateLimitError(ClientError):
    """429 that survived every retry attempt."""


class ServerError(ApiError):
    """5xx that survived every retry attempt."""


_STATUS_EXCEPTIONS: dict[int, type[ApiError]] = {
    401: AuthError,
    403: AuthError,
    404: NotFoundError,
    429: RateLimitError,
}


def exception_for_status(status_code: int) -> type[ApiError]:
    if status_code in _STATUS_EXCEPTIONS:
        return _STATUS_EXCEPTIONS[status_code]
    if 500 <= status_code < 600:
        return ServerError
    if 400 <= status_code < 500:
        return ClientError
    return ApiError
