from __future__ import annotations

import functools
import inspect
import string
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, get_type_hints
from urllib.parse import quote

from pydantic import BaseModel

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
    method: str, path: str
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Turn a method on an `ApiClient` subclass into an actual HTTP request.

    Path placeholders (`{owner}`) are filled from same-named parameters,
    URL-escaped. A `BaseModel` return annotation is what the response is
    parsed into; no annotation (or `-> None`) discards the body and returns
    `None`.
    """
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

        @functools.wraps(func)
        async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(self, *args, **kwargs)
            bound.apply_defaults()

            url = path.format(
                **{name: quote(str(bound.arguments[name]), safe="") for name in path_params}
            )

            response = await self._transport.request(method, url)
            if return_type is None or return_type is type(None):
                return None
            return return_type.model_validate(response.json())

        return wrapper

    return decorator
