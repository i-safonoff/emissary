from __future__ import annotations

import time

import httpx
import pytest
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from emissary import RetryPolicy, ServerError, Transport


async def test_deadline_stops_retrying_once_it_passes(httpserver: HTTPServer) -> None:
    calls = {"n": 0}

    def handler(_request: Request) -> Response:
        calls["n"] += 1
        return Response(status=503)

    httpserver.expect_request("/always-down").respond_with_handler(handler)

    # Attempts are cheap (0.01s each) but the deadline is much smaller than
    # max_attempts * base_delay would need -- if the deadline weren't
    # respected, this would run all 10 attempts; with it, only the ones
    # that fit inside 0.15s do.
    retry = RetryPolicy(max_attempts=10, base_delay=0.1, max_delay=0.1, deadline=0.15)

    start = time.monotonic()
    with pytest.raises(ServerError):
        async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
            await Transport(client, retry=retry).request("GET", "/always-down")
    elapsed = time.monotonic() - start

    assert elapsed < 0.5
    assert calls["n"] < 10


async def test_without_a_deadline_all_attempts_still_run(httpserver: HTTPServer) -> None:
    calls = {"n": 0}

    def handler(_request: Request) -> Response:
        calls["n"] += 1
        return Response(status=503)

    httpserver.expect_request("/always-down").respond_with_handler(handler)
    retry = RetryPolicy(max_attempts=4, base_delay=0.01, max_delay=0.02)

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        with pytest.raises(ServerError):
            await Transport(client, retry=retry).request("GET", "/always-down")

    assert calls["n"] == 4


async def test_a_generous_deadline_does_not_cut_off_a_call_that_would_have_finished(
    httpserver: HTTPServer,
) -> None:
    calls = {"n": 0}

    def handler(_request: Request) -> Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return Response(status=503)
        return Response(b'{"ok": true}', status=200, content_type="application/json")

    httpserver.expect_request("/flaky").respond_with_handler(handler)
    retry = RetryPolicy(max_attempts=3, base_delay=0.01, max_delay=0.02, deadline=5.0)

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        response = await Transport(client, retry=retry).request("GET", "/flaky")

    assert response.json() == {"ok": True}
    assert calls["n"] == 2


def test_deadline_exceeded_is_false_with_no_deadline_set() -> None:
    retry = RetryPolicy()
    assert retry.deadline_exceeded(10_000) is False


def test_deadline_exceeded_compares_against_elapsed_time() -> None:
    retry = RetryPolicy(deadline=1.0)
    assert retry.deadline_exceeded(0.5) is False
    assert retry.deadline_exceeded(1.0) is True
    assert retry.deadline_exceeded(2.0) is True
