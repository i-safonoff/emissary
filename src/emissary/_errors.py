from __future__ import annotations

from typing import Any, Protocol

import httpx


class ErrorMapper(Protocol):
    """Extracts a human-readable message from an error response's body.

    Every API shapes its errors differently -- GitHub's is
    `{"message": ...}`, Stripe's is `{"error": {"message": ...}}` -- so
    there's no single default that would be right more often than it's
    wrong. Without one, exceptions fall back to a status-line message with
    no body content at all.
    """

    def message_for(self, response: httpx.Response) -> str | None:
        """A message from the body, or None to keep the default message."""
        ...


class JsonFieldErrorMapper:
    """An ErrorMapper for the common case: the message is a string at some
    (possibly nested) key in a JSON body. `field` is dot-separated --
    `"message"` for GitHub, `"error.message"` for Stripe.
    """

    def __init__(self, field: str = "message") -> None:
        self._path = field.split(".")

    def message_for(self, response: httpx.Response) -> str | None:
        try:
            data: Any = response.json()
        except ValueError:
            return None
        for key in self._path:
            if not isinstance(data, dict) or key not in data:
                return None
            data = data[key]
        return data if isinstance(data, str) else None
