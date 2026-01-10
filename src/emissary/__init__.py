"""An OOP client framework for external APIs."""

from ._exceptions import (
    ApiError,
    AuthError,
    ClientError,
    NotFoundError,
    RateLimitError,
    ServerError,
)

__all__ = [
    "ApiError",
    "AuthError",
    "ClientError",
    "NotFoundError",
    "RateLimitError",
    "ServerError",
]
__version__ = "0.1.0"
