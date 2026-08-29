"""A real client against the Stripe API, built on emissary -- the second
proof, deliberately picked for what it does differently from GitHub's:
form-encoded bodies instead of JSON, cursor pagination instead of a Link
header, and an idempotency mechanism this project's own Idempotency-Key
already matches natively rather than needing to invent one.

    from emissary.examples.stripe_client import StripeClient

    async with StripeClient(secret_key="sk_test_...") as stripe:
        customer = await stripe.get_customer("cus_...")
        async for c in stripe.list_customers():
            print(c.id, c.email)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel

from emissary import (
    ApiClient,
    BearerTokenAuth,
    CursorPagination,
    JsonFieldErrorMapper,
    endpoint,
)


class Customer(BaseModel):
    id: str
    email: str | None = None
    name: str | None = None
    created: int
    livemode: bool = False
    # Extra fields (invoice_settings, tax_exempt, a dozen more) are
    # dropped, not rejected -- same reasoning as GitHubClient's Repo.


class NewCustomer(BaseModel):
    email: str | None = None
    name: str | None = None


class StripeClient(ApiClient):
    base_url = "https://api.stripe.com/v1"
    # Stripe's error body is {"error": {"type": ..., "message": ...}} --
    # one dotted path away from GitHub's flat {"message": ...}.
    error_mapper = JsonFieldErrorMapper("error.message")

    def __init__(self, secret_key: str, **kwargs: Any) -> None:
        # Stripe's documented alternative to HTTP Basic auth with the
        # secret key as username: Authorization: Bearer sk_test_...
        super().__init__(auth=BearerTokenAuth(secret_key), **kwargs)

    @endpoint("GET", "/customers/{customer_id}")
    async def get_customer(self, customer_id: str) -> Customer:
        raise NotImplementedError

    @endpoint("GET", "/customers", paginate=CursorPagination())
    def list_customers(self) -> AsyncIterator[Customer]:
        raise NotImplementedError

    # idempotent=False here means what it always means in this library --
    # Idempotency-Key attached, minted once and carried across retries --
    # and Stripe happens to be the one real API whose own documented
    # idempotency mechanism is exactly that header. Nothing Stripe-specific
    # was built to make this line up.
    @endpoint("POST", "/customers", idempotent=False, body_encoding="form")
    async def create_customer(self, body: NewCustomer) -> Customer:
        raise NotImplementedError
