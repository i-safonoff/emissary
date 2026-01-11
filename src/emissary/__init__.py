"""An OOP client framework for external APIs."""

from ._exceptions import (
    ApiError,
    AuthError,
    ClientError,
    NotFoundError,
    RateLimitError,
    ServerError,
)
from ._retry import RetryPolicy, parse_retry_after

__all__ = [
    "ApiError",
    "AuthError",
    "ClientError",
    "NotFoundError",
    "RateLimitError",
    "RetryPolicy",
    "ServerError",
    "parse_retry_after",
]
__version__ = "0.1.0"
