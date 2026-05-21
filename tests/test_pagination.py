from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from pydantic import BaseModel
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from emissary import (
    ApiClient,
    CursorPagination,
    EndpointDefinitionError,
    LinkHeaderPagination,
    OffsetPagination,
    PaginationLoopError,
    RetryPolicy,
    endpoint,
)


class Item(BaseModel):
    id: int


async def test_link_header_pagination_follows_rel_next(httpserver: HTTPServer) -> None:
    page1_url = httpserver.url_for("/items?page=2")

    # query_string="" is not optional here: expect_request("/items") with no
    # query_string at all matches *any* query string, including "page=2" --
    # it would shadow the second registration below and this test would
    # loop forever chasing a Link header that points back at itself.
    httpserver.expect_request("/items", query_string="").respond_with_json(
        [{"id": 1}, {"id": 2}],
        headers={"Link": f'<{page1_url}>; rel="next"'},
    )
    httpserver.expect_request("/items", query_string="page=2").respond_with_json([{"id": 3}])

    class Client(ApiClient):
        base_url = httpserver.url_for("")

        @endpoint("GET", "/items", paginate=LinkHeaderPagination())
        def list_items(self) -> AsyncIterator[Item]: ...

    async with Client() as client:
        items = [item async for item in client.list_items()]  # type: ignore[attr-defined]

    assert items == [Item(id=1), Item(id=2), Item(id=3)]


async def test_cursor_pagination_follows_has_more(httpserver: HTTPServer) -> None:
    def handler(request: Request) -> Response:
        after = request.args.get("starting_after")
        if after is None:
            body = {"data": [{"id": 1}, {"id": 2}], "has_more": True}
        elif after == "2":
            body = {"data": [{"id": 3}], "has_more": False}
        else:
            raise AssertionError(f"unexpected cursor {after!r}")
        return Response(json.dumps(body).encode(), status=200, content_type="application/json")

    httpserver.expect_request("/items").respond_with_handler(handler)

    class Client(ApiClient):
        base_url = httpserver.url_for("")

        @endpoint("GET", "/items", paginate=CursorPagination())
        def list_items(self) -> AsyncIterator[Item]: ...

    async with Client() as client:
        items = [item async for item in client.list_items()]  # type: ignore[attr-defined]

    assert items == [Item(id=1), Item(id=2), Item(id=3)]


async def test_offset_pagination_stops_at_total(httpserver: HTTPServer) -> None:
    def handler(request: Request) -> Response:
        offset = int(request.args.get("offset", "0"))
        all_items = [{"id": i} for i in range(5)]
        page = all_items[offset : offset + 2]
        body = {"results": page, "total": len(all_items)}
        return Response(json.dumps(body).encode(), status=200, content_type="application/json")

    httpserver.expect_request("/items").respond_with_handler(handler)

    class Client(ApiClient):
        base_url = httpserver.url_for("")

        @endpoint("GET", "/items", paginate=OffsetPagination())
        def list_items(self) -> AsyncIterator[Item]: ...

    async with Client() as client:
        items = [item async for item in client.list_items()]  # type: ignore[attr-defined]

    assert items == [Item(id=i) for i in range(5)]


async def test_a_flaky_page_mid_pagination_still_retries(httpserver: HTTPServer) -> None:
    calls = {"n": 0}

    def handler(request: Request) -> Response:
        calls["n"] += 1
        if request.args.get("starting_after") == "1" and calls["n"] < 3:
            return Response(status=503)
        after = request.args.get("starting_after")
        if after is None:
            body = b'{"data": [{"id": 1}], "has_more": true}'
        else:
            body = b'{"data": [{"id": 2}], "has_more": false}'
        return Response(body, status=200, content_type="application/json")

    httpserver.expect_request("/items").respond_with_handler(handler)

    class Client(ApiClient):
        base_url = httpserver.url_for("")

        @endpoint("GET", "/items", paginate=CursorPagination())
        def list_items(self) -> AsyncIterator[Item]: ...

    retry = RetryPolicy(max_attempts=5, base_delay=0.01, max_delay=0.02)
    async with Client(retry=retry) as client:
        items = [item async for item in client.list_items()]  # type: ignore[attr-defined]

    assert items == [Item(id=1), Item(id=2)]


async def test_a_cyclic_next_link_raises_instead_of_looping_forever(
    httpserver: HTTPServer,
) -> None:
    # No query_string="" guard this time, on purpose: every request, no
    # matter its query string, gets a Link header pointing back at the
    # plain "/items" URL -- an actual self-referential cycle, the exact
    # shape a real misbehaving API could produce.
    self_url = httpserver.url_for("/items")
    httpserver.expect_request("/items").respond_with_json(
        [{"id": 1}],
        headers={"Link": f'<{self_url}>; rel="next"'},
    )

    class Client(ApiClient):
        base_url = httpserver.url_for("")

        @endpoint("GET", "/items", paginate=LinkHeaderPagination())
        def list_items(self) -> AsyncIterator[Item]: ...

    async with Client() as client:
        with pytest.raises(PaginationLoopError):
            _ = [item async for item in client.list_items()]  # type: ignore[attr-defined]


def test_paginate_needs_an_async_iterator_return_annotation() -> None:
    with pytest.raises(EndpointDefinitionError):

        class BadClient(ApiClient):
            @endpoint("GET", "/items", paginate=LinkHeaderPagination())
            async def list_items(self) -> list[Item]: ...
