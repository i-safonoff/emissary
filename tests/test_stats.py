from __future__ import annotations

import httpx
import pytest
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from emissary import ApiClient, RetryPolicy, ServerError, Transport, endpoint


async def test_a_clean_call_counts_once_with_no_retries_or_errors(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/ok").respond_with_json({})

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        transport = Transport(client)
        await transport.request("GET", "/ok")

    stats = transport.stats()
    assert stats.calls_total == 1
    assert stats.retries_total == 0
    assert stats.errors_total == 0


async def test_a_recovered_flaky_call_counts_its_retries_but_not_as_an_error(
    httpserver: HTTPServer,
) -> None:
    calls = {"n": 0}

    def handler(_request: Request) -> Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return Response(status=503)
        return Response(b"{}", status=200, content_type="application/json")

    httpserver.expect_request("/flaky").respond_with_handler(handler)
    retry = RetryPolicy(max_attempts=5, base_delay=0.01, max_delay=0.02)

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        transport = Transport(client, retry=retry)
        await transport.request("GET", "/flaky")

    stats = transport.stats()
    assert stats.calls_total == 1
    assert stats.retries_total == 2  # two failed attempts before the third succeeded
    assert stats.errors_total == 0


async def test_a_call_that_ultimately_fails_counts_as_one_error(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/always-down").respond_with_data(status=503)
    retry = RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.02)

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        transport = Transport(client, retry=retry)
        with pytest.raises(ServerError):
            await transport.request("GET", "/always-down")

    stats = transport.stats()
    assert stats.calls_total == 1
    assert stats.retries_total == 2  # attempts 1 and 2 retried; attempt 3 gave up
    assert stats.errors_total == 1
    assert stats.retry_ratio == pytest.approx(2.0)


async def test_stats_accumulate_across_multiple_calls(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/ok").respond_with_json({})

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        transport = Transport(client)
        for _ in range(4):
            await transport.request("GET", "/ok")

    assert transport.stats().calls_total == 4


def test_retry_ratio_is_zero_with_no_calls_yet() -> None:
    from emissary import Stats

    assert Stats().retry_ratio == 0.0


async def test_apiclient_stats_delegates_to_its_transport(httpserver: HTTPServer) -> None:
    class Client(ApiClient):
        base_url = httpserver.url_for("")

        @endpoint("GET", "/ok")
        async def ok(self) -> None: ...

    httpserver.expect_request("/ok").respond_with_data(status=204)

    async with Client() as client:
        await client.ok()  # type: ignore[attr-defined]

    assert client.stats().calls_total == 1
