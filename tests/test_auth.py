from __future__ import annotations

import httpx
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from emissary import ApiKeyAuth, BearerTokenAuth


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
