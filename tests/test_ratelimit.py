from __future__ import annotations

import time

import httpx
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from emissary import RateLimiter, RateLimitHeaders, RetryPolicy, Transport


def _response(headers: dict[str, str]) -> httpx.Response:
    request = httpx.Request("GET", "http://example.com/x")
    return httpx.Response(200, headers=headers, request=request)


def test_no_throttle_before_anything_is_observed() -> None:
    limiter = RateLimiter()
    assert limiter._remaining is None  # nothing to wait on yet


async def test_no_throttle_while_budget_is_healthy() -> None:
    limiter = RateLimiter()
    limiter.observe(_response({"X-RateLimit-Remaining": "50", "X-RateLimit-Reset": "9999999999"}))

    start = time.monotonic()
    await limiter.wait_if_needed()
    assert time.monotonic() - start < 0.05


async def test_throttles_until_the_absolute_reset_time(httpserver: HTTPServer) -> None:
    limiter = RateLimiter()
    reset_at = time.time() + 0.1
    limiter.observe(_response({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset_at)}))

    start = time.monotonic()
    await limiter.wait_if_needed()
    elapsed = time.monotonic() - start

    assert elapsed >= 0.08  # close to the 0.1s window, allowing scheduling slack
    assert limiter._remaining is None  # cleared so the next call isn't stuck on stale numbers


async def test_relative_reset_mode_waits_from_now() -> None:
    headers = RateLimitHeaders(reset_is_absolute=False)
    limiter = RateLimiter(headers)
    limiter.observe(_response({"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "0.1"}))

    start = time.monotonic()
    await limiter.wait_if_needed()
    assert time.monotonic() - start >= 0.08


async def test_custom_header_names() -> None:
    headers = RateLimitHeaders(remaining="RateLimit-Remaining", reset="RateLimit-Reset")
    limiter = RateLimiter(headers)
    limiter.observe(_response({"RateLimit-Remaining": "0", "RateLimit-Reset": str(time.time())}))

    assert limiter._remaining == 0


async def test_transport_throttles_the_next_call_after_observing_zero_remaining(
    httpserver: HTTPServer,
) -> None:
    calls = {"n": 0}

    def handler(_request: Request) -> Response:
        calls["n"] += 1
        reset_at = time.time() + 0.15 if calls["n"] == 1 else time.time() + 999
        remaining = "0" if calls["n"] == 1 else "10"
        return Response(
            b"{}",
            status=200,
            content_type="application/json",
            headers={"X-RateLimit-Remaining": remaining, "X-RateLimit-Reset": str(reset_at)},
        )

    httpserver.expect_request("/x").respond_with_handler(handler)

    limiter = RateLimiter()
    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        transport = Transport(client, retry=RetryPolicy(max_attempts=1), rate_limiter=limiter)

        await transport.request("GET", "/x")  # observes remaining=0

        start = time.monotonic()
        await transport.request("GET", "/x")  # should wait out the reset first
        elapsed = time.monotonic() - start

    assert elapsed >= 0.1
    assert calls["n"] == 2
