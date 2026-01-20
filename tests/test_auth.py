from __future__ import annotations

import asyncio

import httpx
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from emissary import ApiKeyAuth, BearerTokenAuth, OAuth2ClientCredentialsAuth


async def test_bearer_token_is_attached(httpserver: HTTPServer) -> None:
    seen = {}

    def handler(request: Request) -> Response:
        seen["auth"] = request.headers.get("Authorization")
        return Response(b"{}", status=200, content_type="application/json")

    httpserver.expect_request("/ok").respond_with_handler(handler)

    auth = BearerTokenAuth("secret-token")
    async with httpx.AsyncClient(base_url=httpserver.url_for(""), auth=auth) as client:
        await client.get("/ok")

    assert seen["auth"] == "Bearer secret-token"


async def test_api_key_is_attached_under_its_own_header(httpserver: HTTPServer) -> None:
    seen = {}

    def handler(request: Request) -> Response:
        seen["key"] = request.headers.get("X-Api-Key")
        return Response(b"{}", status=200, content_type="application/json")

    httpserver.expect_request("/ok").respond_with_handler(handler)

    auth = ApiKeyAuth("X-Api-Key", "my-key")
    async with httpx.AsyncClient(base_url=httpserver.url_for(""), auth=auth) as client:
        await client.get("/ok")

    assert seen["key"] == "my-key"


async def test_oauth2_fetches_a_token_before_the_first_request(httpserver: HTTPServer) -> None:
    token_calls = {"n": 0}

    def token_handler(_request: Request) -> Response:
        token_calls["n"] += 1
        return Response(b'{"access_token": "tok-1"}', status=200, content_type="application/json")

    seen = {}

    def resource_handler(request: Request) -> Response:
        seen["auth"] = request.headers.get("Authorization")
        return Response(b"{}", status=200, content_type="application/json")

    httpserver.expect_request("/token", method="POST").respond_with_handler(token_handler)
    httpserver.expect_request("/resource").respond_with_handler(resource_handler)

    auth = OAuth2ClientCredentialsAuth(
        httpserver.url_for("/token"), client_id="id", client_secret="secret"
    )
    async with httpx.AsyncClient(base_url=httpserver.url_for(""), auth=auth) as client:
        await client.get("/resource")

    assert seen["auth"] == "Bearer tok-1"
    assert token_calls["n"] == 1
    await auth.aclose()


async def test_a_401_triggers_exactly_one_refetch_and_retry(httpserver: HTTPServer) -> None:
    token_calls = {"n": 0}

    def token_handler(_request: Request) -> Response:
        token_calls["n"] += 1
        body = f'{{"access_token": "tok-{token_calls["n"]}"}}'.encode()
        return Response(body, status=200, content_type="application/json")

    def resource_handler(request: Request) -> Response:
        if request.headers.get("Authorization") == "Bearer tok-2":
            return Response(b"{}", status=200, content_type="application/json")
        return Response(status=401)

    httpserver.expect_request("/token", method="POST").respond_with_handler(token_handler)
    httpserver.expect_request("/resource").respond_with_handler(resource_handler)

    auth = OAuth2ClientCredentialsAuth(
        httpserver.url_for("/token"), client_id="id", client_secret="secret"
    )
    async with httpx.AsyncClient(base_url=httpserver.url_for(""), auth=auth) as client:
        response = await client.get("/resource")

    assert response.status_code == 200
    assert token_calls["n"] == 2  # the first (rejected) token, then the refresh
    await auth.aclose()


async def test_concurrent_401s_share_one_token_refresh(httpserver: HTTPServer) -> None:
    token_calls = {"n": 0}
    current_token = {"value": "seed"}

    def token_handler(_request: Request) -> Response:
        # Counts only real HTTP fetches -- kept separate from the
        # out-of-band rotation below, so the assertion measures exactly
        # what it claims to.
        token_calls["n"] += 1
        current_token["value"] = f"tok-{token_calls['n']}"
        body = f'{{"access_token": "{current_token["value"]}"}}'.encode()
        return Response(body, status=200, content_type="application/json")

    def resource_handler(request: Request) -> Response:
        if request.headers.get("Authorization") == f"Bearer {current_token['value']}":
            return Response(b"{}", status=200, content_type="application/json")
        return Response(status=401)

    httpserver.expect_request("/token", method="POST").respond_with_handler(token_handler)
    httpserver.expect_request("/resource").respond_with_handler(resource_handler)

    auth = OAuth2ClientCredentialsAuth(
        httpserver.url_for("/token"), client_id="id", client_secret="secret"
    )
    async with httpx.AsyncClient(base_url=httpserver.url_for(""), auth=auth) as client:
        # Prime a token (one real fetch), then invalidate it out of band --
        # simulating it simply expiring -- so every concurrent request below
        # presents a now-stale token and gets 401 at the same time.
        await client.get("/resource")
        current_token["value"] = "rotated-without-a-fetch"

        responses = await asyncio.gather(*(client.get("/resource") for _ in range(10)))

    assert all(r.status_code == 200 for r in responses)
    # One priming fetch, one coalesced refresh -- not one refresh per
    # concurrent 401.
    assert token_calls["n"] == 2
    await auth.aclose()
