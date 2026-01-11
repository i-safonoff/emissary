from email.utils import formatdate

import pytest

from emissary import parse_retry_after


def test_parses_delay_seconds() -> None:
    assert parse_retry_after("120") == 120.0


def test_parses_http_date() -> None:
    now = 1_700_000_000.0
    date_str = formatdate(now + 60, usegmt=True)

    assert parse_retry_after(date_str, now=now) == pytest.approx(60.0, abs=1.0)


def test_past_http_date_clamps_to_zero() -> None:
    now = 1_700_000_000.0
    date_str = formatdate(now - 60, usegmt=True)

    assert parse_retry_after(date_str, now=now) == 0.0


def test_garbage_returns_none_instead_of_guessing() -> None:
    assert parse_retry_after("not a date or a number") is None
