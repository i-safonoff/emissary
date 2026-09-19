from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Stats:
    """Snapshot of a client's built-in counters.

    Always on, three integers, no dependency -- for anything more (latency
    percentiles, a per-endpoint breakdown), wire `RequestHooks` into a real
    metrics system instead of asking these three numbers to grow into one.
    """

    calls_total: int = 0
    retries_total: int = 0
    errors_total: int = 0

    @property
    def retry_ratio(self) -> float:
        return self.retries_total / self.calls_total if self.calls_total else 0.0


class _Counters:
    """The always-on, dependency-free implementation behind `.stats()`."""

    def __init__(self) -> None:
        self.calls_total = 0
        self.retries_total = 0
        self.errors_total = 0

    def snapshot(self) -> Stats:
        return Stats(self.calls_total, self.retries_total, self.errors_total)
