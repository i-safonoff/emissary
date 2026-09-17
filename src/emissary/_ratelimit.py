from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class RateLimitHeaders:
    """Names of the headers an API reports its rate-limit budget through,
    and whether `reset` is an absolute UNIX timestamp (GitHub's style) or a
    delay in seconds from now. Defaults match GitHub's own header names.
    """

    remaining: str = "X-RateLimit-Remaining"
    reset: str = "X-RateLimit-Reset"
    reset_is_absolute: bool = True


class RateLimiter:
    """Reads an API's own remaining-requests headers on every response and
    waits before the *next* request once the budget is exhausted, instead
    of only reacting to a 429 after it already happened.

    Proactive, not reactive: `RetryPolicy` handles a 429 that already
    arrived; this tries to make one never arrive at all. The two compose --
    a `RateLimiter` doesn't replace retry-on-429, it just makes it rarer.
    """

    def __init__(self, headers: RateLimitHeaders | None = None, *, threshold: int = 0) -> None:
        self._headers = headers or RateLimitHeaders()
        self._threshold = threshold
        self._remaining: int | None = None
        self._reset_at: float | None = None

    def observe(self, response: httpx.Response) -> None:
        """Update the tracked budget from a response's headers. Called
        after every response, successful or not -- the budget a 429 itself
        reports is exactly the number that matters most.
        """
        remaining = response.headers.get(self._headers.remaining)
        if remaining is not None:
            with contextlib.suppress(ValueError):
                self._remaining = int(remaining)

        reset = response.headers.get(self._headers.reset)
        if reset is None:
            return
        try:
            reset_value = float(reset)
        except ValueError:
            return
        if self._headers.reset_is_absolute:
            self._reset_at = reset_value
        else:
            self._reset_at = time.time() + reset_value

    async def wait_if_needed(self) -> None:
        if self._remaining is None or self._remaining > self._threshold or self._reset_at is None:
            return
        delay = self._reset_at - time.time()
        if delay > 0:
            await asyncio.sleep(delay)
        # The budget has presumably refreshed. Don't act on these numbers
        # again until the next observe() reports a fresh remaining count --
        # otherwise every subsequent call would wait for the same reset
        # that already passed.
        self._remaining = None
        self._reset_at = None
