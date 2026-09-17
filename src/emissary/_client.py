from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import httpx

from ._errors import ErrorMapper
from ._hooks import RequestHooks
from ._ratelimit import RateLimiter
from ._retry import RetryPolicy
from ._transport import Transport

if TYPE_CHECKING:
    # typing.Self needs 3.11+; this project supports 3.10. Only used inside
    # a lazily-evaluated annotation (see __future__ import above), so it's
    # never actually imported at runtime -- a type-checking-only import
    # avoids needing typing_extensions as a real dependency just for one
    # name on one Python version.
    from typing_extensions import Self


class ApiClient:
    """Base class for a concrete API client: subclass it, set `base_url`,
    and decorate methods with `@endpoint(...)`.
    """

    base_url: ClassVar[str] = ""
    error_mapper: ClassVar[ErrorMapper | None] = None
    hooks: ClassVar[RequestHooks | None] = None

    def __init__(
        self,
        *,
        auth: httpx.Auth | None = None,
        retry: RetryPolicy | None = None,
        error_mapper: ErrorMapper | None = None,
        rate_limiter: RateLimiter | None = None,
        hooks: RequestHooks | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(base_url=self.base_url, auth=auth)
        self._retry = retry or RetryPolicy()
        self._transport = Transport(
            self._http_client,
            retry=self._retry,
            error_mapper=error_mapper or self.error_mapper,
            # Constructor-only, deliberately not a ClassVar default like
            # error_mapper: a RateLimiter carries mutable state (the
            # observed remaining/reset), and a class-level default would
            # mean every instance of a client class silently shared one
            # budget tracker unless a caller remembered to override it.
            rate_limiter=rate_limiter,
            hooks=hooks or self.hooks,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http_client.aclose()

    async def __aenter__(self) -> Self:
        # Self, not ApiClient: `async with SomeClient(...) as client` needs
        # client typed as SomeClient, or every subclass-specific method
        # disappears the moment it's used as a context manager.
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
