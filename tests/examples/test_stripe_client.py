from __future__ import annotations

import json

import pytest
from examples.stripe_client import Customer, NewCustomer, StripeClient
from pytest_httpserver import HTTPServer
from werkzeug.wrappers import Request, Response

from emissary import NotFoundError

# Real documented shape, from Stripe's own API reference -- trimmed, with
# extras (invoice_settings, tax_exempt, preferred_locales, ...) kept in on
# purpose, same reasoning as the GitHub fixtures.
DOCUMENTED_CUSTOMER = {
    "id": "cus_NffrFeUfNV2Hib",
    "object": "customer",
    "address": None,
    "balance": 0,
    "created": 1680893993,
    "currency": None,
    "delinquent": False,
    "description": None,
    "email": "jennyrosen@example.com",
    "invoice_prefix": "0759376C",
    "invoice_settings": {"custom_fields": None, "default_payment_method": None},
    "livemode": False,
    "metadata": {},
    "name": "Jenny Rosen",
    "next_invoice_sequence": 1,
    "phone": None,
    "preferred_locales": [],
    "tax_exempt": "none",
}

DOCUMENTED_LIST_RESPONSE = {
    "object": "list",
    "url": "/v1/customers",
    "has_more": False,
    "data": [DOCUMENTED_CUSTOMER],
}

DOCUMENTED_ERROR_RESPONSE = {
    "error": {
        "code": "resource_missing",
        "doc_url": "https://stripe.com/docs/error-codes/resource-missing",
        "message": "No such customer: 'cus_invalid'",
        "param": "id",
        "type": "invalid_request_error",
    }
}


def _client_for(httpserver: HTTPServer) -> type[StripeClient]:
    class TestClient(StripeClient):
        base_url = httpserver.url_for("")

    return TestClient


async def test_get_customer_parses_a_documented_response(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/customers/cus_NffrFeUfNV2Hib").respond_with_json(
        DOCUMENTED_CUSTOMER
    )

    async with _client_for(httpserver)(secret_key="sk_test_x") as client:
        customer = await client.get_customer("cus_NffrFeUfNV2Hib")

    assert customer == Customer(
        id="cus_NffrFeUfNV2Hib",
        email="jennyrosen@example.com",
        name="Jenny Rosen",
        created=1680893993,
        livemode=False,
    )


async def test_a_404_carries_stripes_nested_error_message(httpserver: HTTPServer) -> None:
    httpserver.expect_request("/customers/cus_invalid").respond_with_json(
        DOCUMENTED_ERROR_RESPONSE, status=404
    )

    async with _client_for(httpserver)(secret_key="sk_test_x") as client:
        with pytest.raises(NotFoundError, match="No such customer"):
            await client.get_customer("cus_invalid")


async def test_list_customers_follows_cursor_pagination(httpserver: HTTPServer) -> None:
    second_customer = {**DOCUMENTED_CUSTOMER, "id": "cus_second", "email": "second@example.com"}

    def handler(request: Request) -> Response:
        if request.args.get("starting_after") == "cus_NffrFeUfNV2Hib":
            body = {**DOCUMENTED_LIST_RESPONSE, "data": [second_customer], "has_more": False}
        else:
            body = {**DOCUMENTED_LIST_RESPONSE, "has_more": True}
        return Response(json.dumps(body).encode(), status=200, content_type="application/json")

    httpserver.expect_request("/customers").respond_with_handler(handler)

    async with _client_for(httpserver)(secret_key="sk_test_x") as client:
        customers = [c async for c in client.list_customers()]

    assert [c.id for c in customers] == ["cus_NffrFeUfNV2Hib", "cus_second"]


async def test_create_customer_sends_form_encoded_body_with_idempotency_key(
    httpserver: HTTPServer,
) -> None:
    seen = {}

    def handler(request: Request) -> Response:
        seen["content_type"] = request.headers.get("Content-Type", "")
        seen["form"] = request.form.to_dict()
        seen["idempotency_key"] = request.headers.get("Idempotency-Key")
        created = {**DOCUMENTED_CUSTOMER, "id": "cus_new", "email": "new@example.com"}
        return Response(json.dumps(created).encode(), status=200, content_type="application/json")

    httpserver.expect_request("/customers", method="POST").respond_with_handler(handler)

    async with _client_for(httpserver)(secret_key="sk_test_x") as client:
        customer = await client.create_customer(NewCustomer(email="new@example.com"))

    assert seen["content_type"].startswith("application/x-www-form-urlencoded")
    assert seen["form"] == {"email": "new@example.com"}
    assert seen["idempotency_key"] is not None
    assert customer.id == "cus_new"
