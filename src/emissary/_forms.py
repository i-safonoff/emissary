from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import BaseModel


@dataclass(frozen=True)
class UploadFile:
    """A file to send as part of a `body_encoding="multipart"` request. A
    plain container, not a `BaseModel` -- pydantic doesn't need to
    validate raw bytes, and `split_multipart` reads it by attribute rather
    than through pydantic's own serialization.
    """

    filename: str
    content: bytes
    content_type: str = "application/octet-stream"


def split_multipart(
    model: BaseModel,
) -> tuple[dict[str, Any], dict[str, tuple[str, bytes, str]]]:
    """Splits a request body model into httpx's `data=`/`files=` shape for
    a multipart request: any field holding an `UploadFile` becomes a file
    part, everything else becomes a form field. Reads fields directly by
    attribute rather than through `model_dump()`, which has no reason to
    know how to serialize a field type it's never seen before.
    """
    data: dict[str, Any] = {}
    files: dict[str, tuple[str, bytes, str]] = {}
    for name in type(model).model_fields:
        value = getattr(model, name)
        if isinstance(value, UploadFile):
            files[name] = (value.filename, value.content, value.content_type)
        elif value is not None:
            data[name] = value
    return data, files


def flatten_form(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Stripe-style `application/x-www-form-urlencoded` flattening: a
    nested dict becomes bracket-notation keys (`{"metadata": {"k": "v"}}`
    -> `"metadata[k]": "v"`), a list becomes indexed brackets. `None`
    values are dropped -- a form field has no way to carry "explicitly
    null" the way a JSON body does, so sending one would just be wrong,
    not merely redundant.
    """
    flat: dict[str, Any] = {}
    for key, value in data.items():
        if value is None:
            continue
        full_key = f"{prefix}[{key}]" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten_form(value, full_key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                item_key = f"{full_key}[{index}]"
                if isinstance(item, dict):
                    flat.update(flatten_form(item, item_key))
                else:
                    flat[item_key] = item
        else:
            flat[full_key] = value
    return flat
