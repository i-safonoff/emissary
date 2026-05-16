from __future__ import annotations

import dataclasses
import functools
import inspect
import string
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, get_type_hints
from urllib.parse import quote

from pydantic import BaseModel

from ._retry import IDEMPOTENT_METHODS, RetryPolicy

T = TypeVar("T")

_FORMATTER = string.Formatter()


class EndpointDefinitionError(TypeError):
    """Raised when an `@endpoint`-decorated method's own signature is
    ambiguous or otherwise can't be turned into a request. Raised at
    decoration time, not call time -- this is a shape problem, not a data
    problem, and should fail on import rather than on the first call.
    """


def _path_param_names(path: str) -> set[str]:
    return {name for _, name, _, _ in _FORMATTER.parse(path) if name}


def endpoint(
    method: str, path: str, *, idempotent: bool | None = None
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Turn a method on an `ApiClient` subclass into an actual HTTP request.

    Path placeholders (`{owner}`) are filled from same-named parameters,
    URL-escaped. A `BaseModel` return annotation is what the response is
    parsed into; no annotation (or `-> None`) discards the body and returns
    `None`.

    `idempotent` defaults to the method's own idempotency (GET/PUT/DELETE
    True, POST/PATCH False) and controls two things: whether this call is
    eligible for Transport's retries at all, and whether it gets an
    auto-generated `Idempotency-Key` header when it's False.
    """
    resolved_idempotent = (
        idempotent if idempotent is not None else method.upper() in IDEMPOTENT_METHODS
    )
    path_params = _path_param_names(path)

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        signature = inspect.signature(func)
        hints = get_type_hints(func)
        return_type = hints.get("return")
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

            json_body = None
            if body_param is not None:
                json_body = bound.arguments[body_param].model_dump(mode="json")

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
                method, url, json=json_body, headers=headers, retry=call_retry
            )
            if return_type is None or return_type is type(None):
                return None
            return return_type.model_validate(response.json())

        return wrapper

    return decorator
