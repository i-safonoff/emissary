"""An OOP client framework for external APIs."""

from ._auth import ApiKeyAuth, BearerTokenAuth, OAuth2ClientCredentialsAuth
from ._client import ApiClient
from ._endpoint import EndpointDefinitionError, PaginationLoopError, endpoint
from ._errors import ErrorMapper, JsonFieldErrorMapper
from ._exceptions import (
    ApiError,
    AuthError,
    ClientError,
    NotFoundError,
    RateLimitError,
    ServerError,
)
from ._pagination import (
    CursorPagination,
    LinkHeaderPagination,
    OffsetPagination,
    PaginationStrategy,
)
from ._ratelimit import RateLimiter, RateLimitHeaders
from ._retry import RetryPolicy, parse_retry_after
from ._transport import Transport

__all__ = [
    "ApiClient",
    "ApiError",
    "ApiKeyAuth",
    "AuthError",
    "BearerTokenAuth",
    "ClientError",
    "CursorPagination",
    "EndpointDefinitionError",
    "ErrorMapper",
    "JsonFieldErrorMapper",
    "LinkHeaderPagination",
    "NotFoundError",
    "OAuth2ClientCredentialsAuth",
    "OffsetPagination",
    "PaginationLoopError",
    "PaginationStrategy",
    "RateLimitError",
    "RateLimitHeaders",
    "RateLimiter",
    "RetryPolicy",
    "ServerError",
    "Transport",
    "endpoint",
    "parse_retry_after",
]
__version__ = "0.2.0"
