from __future__ import annotations

import dataclasses
import functools
import inspect
import string
import uuid
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator, Callable
from typing import Any, Literal, get_args, get_origin, get_type_hints
from urllib.parse import quote

from pydantic import BaseModel

from ._forms import flatten_form
from ._pagination import PaginationStrategy
from ._retry import IDEMPOTENT_METHODS, RetryPolicy

_FORMATTER = string.Formatter()

# AsyncIterator[X], AsyncIterable[X] and AsyncGenerator[X, ...] all count as
# "yields X" for a paginated endpoint's return annotation.
_ASYNC_ITERATION_ORIGINS = {AsyncIterator, AsyncIterable, AsyncGenerator}


class EndpointDefinitionError(TypeError):
    """Raised when an `@endpoint`-decorated method's own signature is
    ambiguous or otherwise can't be turned into a request. Raised at
    decoration time, not call time -- this is a shape problem, not a data
    problem, and should fail on import rather than on the first call.
    """


class PaginationLoopError(RuntimeError):
    """Raised when pagination would fetch a URL it already fetched --
    a cyclic (or self-referential) next-page link, not a legitimately
    long result set. Almost always a bug on the API's side.
    """


def _path_param_names(path: str) -> set[str]:
    return {name for _, name, _, _ in _FORMATTER.parse(path) if name}


def _paginated_item_type(func: Callable[..., Any], return_type: Any) -> type[BaseModel]:
    origin = get_origin(return_type)
    args = get_args(return_type)
    if origin not in _ASYNC_ITERATION_ORIGINS or not args:
        raise EndpointDefinitionError(
            f"{func.__qualname__} has paginate=, so it needs a return annotation "
            f"of AsyncIterator[YourModel] (or AsyncIterable/AsyncGenerator) -- got "
            f"{return_type!r}"
        )
    item_type = args[0]
    if not (isinstance(item_type, type) and issubclass(item_type, BaseModel)):
        raise EndpointDefinitionError(
            f"{func.__qualname__} yields {item_type!r}, but paginate= needs a BaseModel subclass"
        )
    return item_type


def endpoint(
    method: str,
    path: str,
    *,
    idempotent: bool | None = None,
    paginate: PaginationStrategy | None = None,
    body_encoding: Literal["json", "form"] = "json",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Turn a method on an `ApiClient` subclass into an actual HTTP request.

    Path placeholders (`{owner}`) are filled from same-named parameters,
    URL-escaped. A `BaseModel` return annotation is what the response is
    parsed into; no annotation (or `-> None`) discards the body and returns
    `None`.

    `idempotent` defaults to the method's own idempotency (GET/PUT/DELETE
    True, POST/PATCH False) and controls two things: whether this call is
    eligible for Transport's retries at all, and whether it gets an
    auto-generated `Idempotency-Key` header when it's False.

    `paginate` turns the method into an async generator instead of a single
    call: the return annotation must be `AsyncIterator[YourModel]` (or
    `AsyncIterable`/`AsyncGenerator`), and calling it yields validated
    items across as many pages as the strategy says exist. Each page fetch
    goes through the same Transport, so a flaky page mid-pagination retries
    exactly like any other request would.

    `body_encoding` defaults to `"json"`. Not every API takes one: Stripe's
    v1 API is `application/x-www-form-urlencoded`, with nested objects as
    bracket-notation keys (`metadata[key]=value`) -- `"form"` sends the
    request body that way instead.
    """
    resolved_idempotent = (
        idempotent if idempotent is not None else method.upper() in IDEMPOTENT_METHODS
    )
    path_params = _path_param_names(path)

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(func)
        hints = get_type_hints(func)
        return_type = hints.get("return")

        if paginate is not None:
            return _wrap_paginated(
                func, signature, return_type, method, path, path_params, paginate
            )

        return_is_model = isinstance(return_type, type) and issubclass(return_type, BaseModel)
        if return_type is not None and return_type is not type(None) and not return_is_model:
            raise EndpointDefinitionError(
                f"{func.__qualname__} returns {return_type!r}, but @endpoint needs "
                "either no return annotation (or -> None) or a BaseModel subclass"
            )

        body_params = [
            name
            for name, hint in hints.items()
            if name not in ("self", "return")
            and isinstance(hint, type)
            and issubclass(hint, BaseModel)
        ]
        if len(body_params) > 1:
            raise EndpointDefinitionError(
                f"{func.__qualname__} takes more than one BaseModel parameter "
                f"({', '.join(body_params)}) -- at most one can be the request body"
            )
        body_param = body_params[0] if body_params else None

        @functools.wraps(func)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(self, *args, **kwargs)
            bound.apply_defaults()

            url = path.format(
                **{name: quote(str(bound.arguments[name]), safe="") for name in path_params}
            )

            body_kwargs: dict[str, Any] = {}
            if body_param is not None:
                raw_body = bound.arguments[body_param].model_dump(mode="json")
                if body_encoding == "form":
                    body_kwargs["data"] = flatten_form(raw_body)
                else:
                    body_kwargs["json"] = raw_body

            headers: dict[str, str] = {}
            call_retry: RetryPolicy | None = None
            if not resolved_idempotent:
                # Generated once, before any retry, and carried on every
                # attempt of this same logical call -- a fresh key per
                # retry would defeat the entire point of having one: the
                # server would see N different requests instead of N
                # attempts at the same one.
                headers["Idempotency-Key"] = str(uuid.uuid4())
                call_retry = dataclasses.replace(self._retry, idempotent_only=False)

            response = await self._transport.request(
                method, url, headers=headers, retry=call_retry, **body_kwargs
            )
            if return_type is None or return_type is type(None):
                return None
            return return_type.model_validate(response.json())

        return wrapper

    return decorator


def _wrap_paginated(
    func: Callable[..., Any],
    signature: inspect.Signature,
    return_type: Any,
    method: str,
    path: str,
    path_params: set[str],
    paginate: PaginationStrategy,
) -> Callable[..., AsyncIterator[Any]]:
    item_type = _paginated_item_type(func, return_type)

    @functools.wraps(func)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        url: Any = path.format(
            **{name: quote(str(bound.arguments[name]), safe="") for name in path_params}
        )
        # A misbehaving (or self-referential, or actively hostile)
        # next-page link turns this loop into an unbounded stream of
        # requests with nothing else to stop it. Cheaper than a page-count
        # cap, and doesn't need tuning: a legitimate pagination never
        # revisits a URL, so any repeat is already proof of a cycle.
        seen_urls: set[str] = set()
        while url is not None:
            url_str = str(url)
            if url_str in seen_urls:
                raise PaginationLoopError(
                    f"pagination for {func.__qualname__} revisited {url_str!r} -- "
                    "the next-page link is cyclic"
                )
            seen_urls.add(url_str)
            response = await self._transport.request(method, url)
            for raw_item in paginate.items(response):
                yield item_type.model_validate(raw_item)
            url = paginate.next_url(response)

    return wrapper
