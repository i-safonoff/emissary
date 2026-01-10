import pytest

from emissary import ApiError, AuthError, ClientError, NotFoundError, RateLimitError, ServerError
from emissary._exceptions import exception_for_status


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, AuthError),
        (403, AuthError),
        (404, NotFoundError),
        (429, RateLimitError),
        (400, ClientError),
        (418, ClientError),
        (500, ServerError),
        (503, ServerError),
        (200, ApiError),
        (301, ApiError),
    ],
)
def test_exception_for_status(status: int, expected: type[ApiError]) -> None:
    assert exception_for_status(status) is expected
