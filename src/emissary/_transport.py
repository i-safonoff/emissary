from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ._exceptions import exception_for_status
from ._retry import RetryPolicy


class Transport:
    """Wraps an `httpx.AsyncClient` with uniform retry behavior applied to
    every request that goes through it. Owns no connection lifecycle --
    pass in a client you created, close it yourself.
    """

    def __init__(self, client: httpx.AsyncClient, *, retry: RetryPolicy | None = None) -> None:
        self._client = client
        self._retry = retry or RetryPolicy()

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._client.request(method, url, **kwargs)
            except self._retry.retry_on_exceptions:
                if attempt >= self._retry.max_attempts or not self._retry.allows(method):
                    raise
                await asyncio.sleep(self._retry.delay_for(attempt, None))
                continue

            if (
                response.status_code in self._retry.retry_on_status
                and attempt < self._retry.max_attempts
                and self._retry.allows(method)
            ):
                await response.aclose()
                await asyncio.sleep(
                    self._retry.delay_for(attempt, response.headers.get("retry-after"))
                )
                continue

            if response.status_code >= 400:
                exc_cls = exception_for_status(response.status_code)
                message = f"{response.status_code} from {method.upper()} {url}"
                raise exc_cls(message, status_code=response.status_code, response=response)

            return response
