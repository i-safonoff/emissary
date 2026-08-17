from __future__ import annotations

from typing import ClassVar

import httpx

from ._errors import ErrorMapper
from ._retry import RetryPolicy
from ._transport import Transport


class ApiClient:
    """Base class for a concrete API client: subclass it, set `base_url`,
    and decorate methods with `@endpoint(...)`.
    """

    base_url: ClassVar[str] = ""
    error_mapper: ClassVar[ErrorMapper | None] = None

    def __init__(
        self,
        *,
        auth: httpx.Auth | None = None,
        retry: RetryPolicy | None = None,
        error_mapper: ErrorMapper | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(base_url=self.base_url, auth=auth)
        self._retry = retry or RetryPolicy()
        self._transport = Transport(
            self._http_client,
            retry=self._retry,
            error_mapper=error_mapper or self.error_mapper,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http_client.aclose()

    async def __aenter__(self) -> ApiClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
