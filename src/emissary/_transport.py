from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ._errors import ErrorMapper
from ._exceptions import exception_for_status
from ._hooks import RequestHooks
from ._ratelimit import RateLimiter
from ._retry import RetryPolicy


class Transport:
    """Wraps an `httpx.AsyncClient` with uniform retry behavior applied to
    every request that goes through it. Owns no connection lifecycle --
    pass in a client you created, close it yourself.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        retry: RetryPolicy | None = None,
        error_mapper: ErrorMapper | None = None,
        rate_limiter: RateLimiter | None = None,
        hooks: RequestHooks | None = None,
    ) -> None:
        self._client = client
        self._retry = retry or RetryPolicy()
        self._error_mapper = error_mapper
        self._rate_limiter = rate_limiter
        self._hooks = hooks

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
            if self._rate_limiter is not None:
                # Checked before every attempt, not just the first: the
                # budget a previous call observed can already be exhausted
                # before this call's own first request goes out.
                await self._rate_limiter.wait_if_needed()
            # build_request() + send() instead of the client.request()
            # convenience method -- the only way to get the real Request
            # object a hook can look at, since request() builds one
            # internally and never hands it back.
            request = self._client.build_request(method, url, **kwargs)
            if self._hooks is not None:
                self._hooks.on_request(request, attempt=attempt)
            try:
                response = await self._client.send(request)
            except active_retry.retry_on_exceptions as exc:
                if self._hooks is not None:
                    self._hooks.on_error(request, exc, attempt=attempt)
                if attempt >= active_retry.max_attempts or not active_retry.allows(method):
                    raise
                await asyncio.sleep(active_retry.delay_for(attempt, None))
                continue

            if self._hooks is not None:
                self._hooks.on_response(response, attempt=attempt)

            if self._rate_limiter is not None:
                self._rate_limiter.observe(response)

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
                if self._error_mapper is not None:
                    detail = self._error_mapper.message_for(response)
                    if detail:
                        message = f"{message}: {detail}"
                raise exc_cls(message, status_code=response.status_code, response=response)

            return response
