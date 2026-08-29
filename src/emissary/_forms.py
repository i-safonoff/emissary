from __future__ import annotations

from typing import Any


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
