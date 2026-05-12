"""An OOP client framework for external APIs."""

from ._auth import ApiKeyAuth, BearerTokenAuth, OAuth2ClientCredentialsAuth
from ._client import ApiClient
from ._endpoint import EndpointDefinitionError, endpoint
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
    "ApiClient",
    "ApiError",
    "ApiKeyAuth",
    "AuthError",
    "BearerTokenAuth",
    "ClientError",
    "EndpointDefinitionError",
    "NotFoundError",
    "OAuth2ClientCredentialsAuth",
    "RateLimitError",
    "RetryPolicy",
    "ServerError",
    "Transport",
    "endpoint",
    "parse_retry_after",
]
__version__ = "0.1.0"
