from __future__ import annotations

from emissary._forms import flatten_form


def test_flat_fields_pass_through_unchanged() -> None:
    assert flatten_form({"email": "a@example.com", "name": "A"}) == {
        "email": "a@example.com",
        "name": "A",
    }


def test_nested_dict_becomes_bracket_notation() -> None:
    assert flatten_form({"metadata": {"order_id": "6735"}}) == {"metadata[order_id]": "6735"}


def test_nested_lists_get_indexed_brackets() -> None:
    assert flatten_form({"items": [{"price": "p1"}, {"price": "p2"}]}) == {
        "items[0][price]": "p1",
        "items[1][price]": "p2",
    }


def test_none_values_are_dropped_not_sent_as_empty() -> None:
    assert flatten_form({"name": "A", "phone": None}) == {"name": "A"}
