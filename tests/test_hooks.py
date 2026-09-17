from __future__ import annotations

import httpx
import pytest
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from emissary import RequestHooks, RetryPolicy, ServerError, Transport


class Recorder(RequestHooks):
    def __init__(self) -> None:
        self.requests: list[tuple[str, int]] = []
        self.responses: list[tuple[int, int]] = []
        self.errors: list[tuple[str, int]] = []

    def on_request(self, request: httpx.Request, *, attempt: int) -> None:
        self.requests.append((str(request.url), attempt))

    def on_response(self, response: httpx.Response, *, attempt: int) -> None:
        self.responses.append((response.status_code, attempt))

    def on_error(self, request: httpx.Request, exc: Exception, *, attempt: int) -> None:
        self.errors.append((type(exc).__name__, attempt))


async def test_on_request_and_on_response_fire_for_a_successful_call(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/ok").respond_with_json({"status": "fine"})
    recorder = Recorder()

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        await Transport(client, hooks=recorder).request("GET", "/ok")

    assert len(recorder.requests) == 1
    assert recorder.requests[0][1] == 1
    assert recorder.responses == [(200, 1)]
    assert recorder.errors == []


async def test_hooks_fire_on_every_retry_attempt_not_just_the_last(
    httpserver: HTTPServer,
) -> None:
    calls = {"n": 0}

    def handler(_request: Request) -> Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return Response(status=503)
        return Response(b'{"ok": true}', status=200, content_type="application/json")

    httpserver.expect_request("/flaky").respond_with_handler(handler)
    recorder = Recorder()
    retry = RetryPolicy(max_attempts=5, base_delay=0.01, max_delay=0.02)

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        await Transport(client, retry=retry, hooks=recorder).request("GET", "/flaky")

    assert [attempt for _, attempt in recorder.requests] == [1, 2, 3]
    assert [(status, attempt) for status, attempt in recorder.responses] == [
        (503, 1),
        (503, 2),
        (200, 3),
    ]


async def test_on_response_fires_even_for_a_final_error_response(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/always-down").respond_with_data(status=503)
    recorder = Recorder()
    retry = RetryPolicy(max_attempts=1)

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        with pytest.raises(ServerError):
            await Transport(client, retry=retry, hooks=recorder).request("GET", "/always-down")

    assert recorder.responses == [(503, 1)]


async def test_a_hook_that_only_overrides_on_request_is_fine(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/ok").respond_with_json({})
    seen = []

    class OnlyLogsRequests(RequestHooks):
        def on_request(self, request: httpx.Request, *, attempt: int) -> None:
            seen.append(str(request.url))

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        await Transport(client, hooks=OnlyLogsRequests()).request("GET", "/ok")

    assert len(seen) == 1
