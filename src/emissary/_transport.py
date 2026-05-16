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

    async def request(
        self, method: str, url: str, *, retry: RetryPolicy | None = None, **kwargs: Any
    ) -> httpx.Response:
        # A per-call override, not just the client-wide default: an
        # endpoint carrying its own idempotency key is safe to retry even
        # when its method normally wouldn't be -- see endpoint()'s
        # idempotent= handling.
        active_retry = retry or self._retry
        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._client.request(method, url, **kwargs)
            except active_retry.retry_on_exceptions:
                if attempt >= active_retry.max_attempts or not active_retry.allows(method):
                    raise
                await asyncio.sleep(active_retry.delay_for(attempt, None))
                continue

            if (
                response.status_code in active_retry.retry_on_status
                and attempt < active_retry.max_attempts
                and active_retry.allows(method)
            ):
                await response.aclose()
                await asyncio.sleep(
                    active_retry.delay_for(attempt, response.headers.get("retry-after"))
                )
                continue

            if response.status_code >= 400:
                exc_cls = exception_for_status(response.status_code)
                message = f"{response.status_code} from {method.upper()} {url}"
                raise exc_cls(message, status_code=response.status_code, response=response)

            return response
