from __future__ import annotations

from collections.abc import AsyncGenerator, Generator

import httpx
from unicall import CoalescedFunction, unicall

from ._retry import RetryPolicy
from ._transport import Transport


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


class OAuth2ClientCredentialsAuth(httpx.Auth):
    """Client-credentials OAuth2: fetches a token, attaches it as a Bearer
    header, and fetches a fresh one if a request comes back 401.

    Concurrent requests that all present an expired token at once each
    independently see the 401 and each independently decide to refresh --
    naively, that's N refresh calls to the token endpoint for one actual
    expiry. The refresh goes through unicall so they share one instead.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._owns_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient()
        # Retrying the token POST is safe even though POST isn't normally
        # idempotent by this library's own default: asking for another
        # client-credentials token has no side effect beyond issuing one.
        self._transport = Transport(self._http_client, retry=RetryPolicy(idempotent_only=False))
        self._token: str | None = None
        self._fetch: CoalescedFunction[[], str] = unicall()(self._fetch_token)

    async def _fetch_token(self) -> str:
        response = await self._transport.request(
            "POST",
            self._token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
        )
        return str(response.json()["access_token"])

    async def async_auth_flow(
        self, request: httpx.Request
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        if self._token is None:
            self._token = await self._fetch()
        request.headers["Authorization"] = f"Bearer {self._token}"
        response = yield request

        if response.status_code == 401:
            self._token = await self._fetch()
            request.headers["Authorization"] = f"Bearer {self._token}"
            yield request

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http_client.aclose()
