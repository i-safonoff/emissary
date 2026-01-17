from __future__ import annotations

from collections.abc import Generator

import httpx


class BearerTokenAuth(httpx.Auth):
    """A fixed bearer token, attached to every request."""

    def __init__(self, token: str) -> None:
        self._token = token

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers["Authorization"] = f"Bearer {self._token}"
        yield request


class ApiKeyAuth(httpx.Auth):
    """An API key in a header, under whatever name the API calls it."""

    def __init__(self, header_name: str, api_key: str) -> None:
        self._header_name = header_name
        self._api_key = api_key

    def auth_flow(self, request: httpx.Request) -> Generator[httpx.Request, httpx.Response, None]:
        request.headers[self._header_name] = self._api_key
        yield request
