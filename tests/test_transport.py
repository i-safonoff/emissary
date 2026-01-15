from __future__ import annotations

import httpx
import pytest
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from emissary import NotFoundError, RetryPolicy, ServerError, Transport

FAST_RETRY = RetryPolicy(max_attempts=5, base_delay=0.01, max_delay=0.02)


async def test_successful_request_passes_through(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/ok").respond_with_json({"status": "fine"})

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        response = await Transport(client).request("GET", "/ok")

    assert response.json() == {"status": "fine"}


async def test_retries_a_flaky_503_then_succeeds(httpserver: HTTPServer) -> None:
    calls = {"n": 0}

    def handler(_request: Request) -> Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return Response(status=503)
        return Response(b'{"status": "recovered"}', status=200, content_type="application/json")

    httpserver.expect_request("/flaky").respond_with_handler(handler)

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        response = await Transport(client, retry=FAST_RETRY).request("GET", "/flaky")

    assert response.json() == {"status": "recovered"}
    assert calls["n"] == 3


async def test_exhausting_retries_raises_server_error(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/always-down").respond_with_data(status=503)

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        retry = RetryPolicy(max_attempts=2, base_delay=0.01, max_delay=0.02)
        with pytest.raises(ServerError):
            await Transport(client, retry=retry).request("GET", "/always-down")


async def test_a_post_is_not_retried_by_default(httpserver: HTTPServer) -> None:
    calls = {"n": 0}

    def handler(_request: Request) -> Response:
        calls["n"] += 1
        return Response(status=503)

    httpserver.expect_request("/create", method="POST").respond_with_handler(handler)

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        with pytest.raises(ServerError):
            await Transport(client, retry=FAST_RETRY).request("POST", "/create")

    assert calls["n"] == 1


async def test_a_post_is_retried_when_opted_in(httpserver: HTTPServer) -> None:
    calls = {"n": 0}

    def handler(_request: Request) -> Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return Response(status=503)
        return Response(b'{"created": true}', status=201, content_type="application/json")

    httpserver.expect_request("/create", method="POST").respond_with_handler(handler)

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        retry = RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.02, idempotent_only=False)
        response = await Transport(client, retry=retry).request("POST", "/create")

    assert response.json() == {"created": True}
    assert calls["n"] == 2


async def test_a_404_is_not_retried_and_maps_to_not_found_error(httpserver: HTTPServer) -> None:
    calls = {"n": 0}

    def handler(_request: Request) -> Response:
        calls["n"] += 1
        return Response(status=404)

    httpserver.expect_request("/missing").respond_with_handler(handler)

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        with pytest.raises(NotFoundError):
            await Transport(client, retry=FAST_RETRY).request("GET", "/missing")

    assert calls["n"] == 1


async def test_retry_after_header_is_honored(httpserver: HTTPServer) -> None:
    calls = {"n": 0}

    def handler(_request: Request) -> Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return Response(status=429, headers={"Retry-After": "0"})
        return Response(b'{"ok": true}', status=200, content_type="application/json")

    httpserver.expect_request("/limited").respond_with_handler(handler)

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        # base_delay=5.0: if the header were ignored, this would be slow.
        retry = RetryPolicy(max_attempts=3, base_delay=5.0)
        response = await Transport(client, retry=retry).request("GET", "/limited")

    assert response.json() == {"ok": True}
    assert calls["n"] == 2
