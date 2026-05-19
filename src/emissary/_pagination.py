from __future__ import annotations

from typing import Any, Protocol

import httpx


class PaginationStrategy(Protocol):
    """What `@endpoint(..., paginate=...)` needs from a pagination scheme.

    Both methods take only the response that was just fetched -- the
    original request URL and its query params are reachable from
    `response.request.url`, which is enough to compute the next page's URL
    without this class needing to be told anything about the request shape
    up front.
    """

    def items(self, response: httpx.Response) -> list[Any]:
        """This page's raw items, from the response body."""
        ...

    def next_url(self, response: httpx.Response) -> httpx.URL | None:
        """The next page's URL, or None if this was the last page."""
        ...


class LinkHeaderPagination:
    """Pagination via the `Link` response header (RFC 8288), `rel="next"`
    -- GitHub's style. The response body is expected to be a JSON array.

    Parsing is httpx's own `Response.links`, not a hand-rolled one: RFC
    8288 allows quoted parameters and multiple relations per header, and
    that parser already exists and is already tested.
    """

    def items(self, response: httpx.Response) -> list[Any]:
        data = response.json()
        if not isinstance(data, list):
            raise TypeError(
                f"LinkHeaderPagination expected a JSON array, got {type(data).__name__}"
            )
        return data

    def next_url(self, response: httpx.Response) -> httpx.URL | None:
        next_link = response.links.get("next")
        return httpx.URL(next_link["url"]) if next_link else None


class CursorPagination:
    """Cursor pagination via a `has_more` flag and an id-based cursor --
    Stripe's style: `{"data": [...], "has_more": true}`, and the next page
    asks for `starting_after=<last item's id>`.
    """

    def __init__(
        self,
        *,
        items_key: str = "data",
        has_more_key: str = "has_more",
        cursor_param: str = "starting_after",
        id_key: str = "id",
    ) -> None:
        self._items_key = items_key
        self._has_more_key = has_more_key
        self._cursor_param = cursor_param
        self._id_key = id_key

    def items(self, response: httpx.Response) -> list[Any]:
        return list(response.json()[self._items_key])

    def next_url(self, response: httpx.Response) -> httpx.URL | None:
        data = response.json()
        page_items = data[self._items_key]
        # has_more=True with zero items would loop forever on the same
        # cursor otherwise -- an API inconsistency, but one that turns into
        # an infinite empty-page loop instead of a clear failure without
        # this check.
        if not data.get(self._has_more_key) or not page_items:
            return None
        last_id = page_items[-1][self._id_key]
        return response.request.url.copy_merge_params({self._cursor_param: last_id})


class OffsetPagination:
    """Offset/limit pagination against a known total count."""

    def __init__(
        self,
        *,
        items_key: str = "results",
        total_key: str = "total",
        offset_param: str = "offset",
        limit_param: str = "limit",
    ) -> None:
        self._items_key = items_key
        self._total_key = total_key
        self._offset_param = offset_param
        self._limit_param = limit_param

    def items(self, response: httpx.Response) -> list[Any]:
        return list(response.json()[self._items_key])

    def next_url(self, response: httpx.Response) -> httpx.URL | None:
        data = response.json()
        page_items = data[self._items_key]
        params = httpx.QueryParams(response.request.url.query)
        current_offset = int(params.get(self._offset_param, "0"))
        limit = int(params.get(self._limit_param, len(page_items)))
        next_offset = current_offset + len(page_items)
        if not page_items or next_offset >= data[self._total_key]:
            return None
        return response.request.url.copy_merge_params(
            {self._offset_param: next_offset, self._limit_param: limit}
        )
