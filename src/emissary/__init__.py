"""An OOP client framework for external APIs."""

from ._auth import ApiKeyAuth, BearerTokenAuth
from ._exceptions import (
    ApiError,
    AuthError,
    ClientError,
    NotFoundError,
    RateLimitError,
    ServerError,
)
from ._retry import RetryPolicy, parse_retry_after
from ._transport import Transport

__all__ = [
    "ApiError",
    "ApiKeyAuth",
    "AuthError",
    "BearerTokenAuth",
    "ClientError",
    "NotFoundError",
    "RateLimitError",
    "RetryPolicy",
    "ServerError",
    "Transport",
    "parse_retry_after",
]
__version__ = "0.1.0"
