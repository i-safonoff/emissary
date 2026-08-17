from __future__ import annotations

import httpx
import pytest
from pytest_httpserver import HTTPServer

from emissary import JsonFieldErrorMapper, NotFoundError, RetryPolicy, Transport


async def test_a_flat_field_message_is_appended_to_the_exception(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/missing").respond_with_json(
        {"message": "Not Found", "documentation_url": "https://docs.example.com"},
        status=404,
    )

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        transport = Transport(
            client,
            retry=RetryPolicy(max_attempts=1),
            error_mapper=JsonFieldErrorMapper("message"),
        )
        with pytest.raises(NotFoundError, match="Not Found"):
            await transport.request("GET", "/missing")


async def test_a_nested_field_message_is_appended_to_the_exception(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/missing").respond_with_json(
        {"error": {"type": "invalid_request_error", "message": "No such customer"}},
        status=404,
    )

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        transport = Transport(
            client,
            retry=RetryPolicy(max_attempts=1),
            error_mapper=JsonFieldErrorMapper("error.message"),
        )
        with pytest.raises(NotFoundError, match="No such customer"):
            await transport.request("GET", "/missing")


async def test_a_missing_field_falls_back_to_the_default_message(
    httpserver: HTTPServer,
) -> None:
    httpserver.expect_request("/missing").respond_with_data(status=404)

    async with httpx.AsyncClient(base_url=httpserver.url_for("")) as client:
        transport = Transport(
            client,
            retry=RetryPolicy(max_attempts=1),
            error_mapper=JsonFieldErrorMapper("message"),
        )
        with pytest.raises(NotFoundError, match=r"^404 from GET /missing$"):
            await transport.request("GET", "/missing")
