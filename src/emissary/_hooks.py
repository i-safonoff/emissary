from __future__ import annotations

import httpx


class RequestHooks:
    """Override any subset of these to observe requests as they happen.

    Every hook fires on every attempt, not just the final one -- a retry
    storm should be visible in whatever's watching, not hidden behind
    whichever attempt eventually succeeded. The no-op defaults mean a
    subclass only needs to implement the one it cares about.
    """

    def on_request(self, request: httpx.Request, *, attempt: int) -> None:
        pass

    def on_response(self, response: httpx.Response, *, attempt: int) -> None:
        pass

    def on_error(self, request: httpx.Request, exc: Exception, *, attempt: int) -> None:
        pass
