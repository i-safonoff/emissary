from __future__ import annotations

import email.utils
import random
import time
from dataclasses import dataclass
from datetime import timezone

import httpx

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})


def parse_retry_after(value: str, *, now: float | None = None) -> float | None:
    """Seconds to wait, from a `Retry-After` header value.

    RFC 9110 10.2.3 allows two shapes: an integer number of seconds, or an
    HTTP-date. Returns None for anything that's neither, rather than
    guessing.
    """
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        dt = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    reference = now if now is not None else time.time()
    return max(dt.timestamp() - reference, 0.0)


@dataclass(frozen=True)
class RetryPolicy:
    """How and when a Transport retries a request.

    `idempotent_only` defaults to True on purpose: retrying a POST that
    already reached the server risks running it twice (creating two orders,
    say). Set it False only for endpoints you know are safe to repeat --
    or that carry their own idempotency key.
    """

    max_attempts: int = 3
    retry_on_status: frozenset[int] = frozenset({429, 502, 503, 504})
    retry_on_exceptions: tuple[type[Exception], ...] = (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.RemoteProtocolError,
    )
    base_delay: float = 0.5
    max_delay: float = 30.0
    jitter: float = 0.2
    idempotent_only: bool = True
    # Total seconds across every attempt and every backoff sleep, measured
    # from the first attempt -- not a per-attempt timeout. That's a
    # different thing (httpx's own timeout=, on the client or per call)
    # and the two compose: this bounds retry overhead, that bounds how
    # long any one request is allowed to hang.
    deadline: float | None = None

    def allows(self, method: str) -> bool:
        return not self.idempotent_only or method.upper() in IDEMPOTENT_METHODS

    def deadline_exceeded(self, elapsed: float) -> bool:
        return self.deadline is not None and elapsed >= self.deadline

    def delay_for(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None:
            parsed = parse_retry_after(retry_after)
            if parsed is not None:
                return parsed
        base = min(self.max_delay, self.base_delay * (2.0 ** (attempt - 1)))
        spread = base * self.jitter
        return max(0.0, base + random.uniform(-spread, spread))
