# emissary

**An OOP client framework for external APIs — endpoints as typed objects,
retries and pagination handled once instead of once per integration.**

[![CI](https://github.com/i-safonoff/emissary/actions/workflows/ci.yml/badge.svg)](https://github.com/i-safonoff/emissary/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![httpx](https://img.shields.io/badge/httpx-native-009688)
![Pydantic](https://img.shields.io/badge/pydantic-v2-e92063)
![Tests](https://img.shields.io/badge/tests-56%20passing-brightgreen)
![Typed](https://img.shields.io/badge/typed-py.typed-informational)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

---

## Contents

- [Why I built this](#why-i-built-this)
- [What it does](#what-it-does)
- [Transport and retries](#transport-and-retries)
- [Auth](#auth)
- [Endpoints as objects](#endpoints-as-objects)
- [Pagination](#pagination)
- [Proving it against real APIs](#proving-it-against-real-apis)
- [The branches](#the-branches)
- [Quickstart](#quickstart)
- [Testing it](#testing-it)
- [Project layout](#project-layout)
- [What I would do differently at scale](#what-i-would-do-differently-at-scale)

## Why I built this

Every job with more than one external API in it ends up writing the same
five things again for each one: a retry loop, a way to attach auth, a
pagination cursor of some shape, an idempotency key for anything that
writes, and an exception hierarchy that hides which HTTP library is
underneath. Usually all five, slightly differently, once per integration,
because each one grew out of whichever endpoint needed it first.

This is that plumbing built once, on top of `httpx` and `pydantic` rather
than instead of them — an endpoint is a decorated method with a return type,
not a hand-written `client.post(url, json=..., headers=...)` and a
`response.json()` cast. Two real APIs prove it: GitHub (JSON, Link-header
pagination, a personal token) and Stripe (form-encoded bodies, cursor
pagination, a secret key) — picked for how differently they're shaped, not
in spite of it.

## What it does

```python
from emissary.examples.github_client import GitHubClient

async with GitHubClient(token="ghp_...") as gh:
    repo = await gh.get_repo("i-safonoff", "unicall")

    async for issue in gh.list_issues("i-safonoff", "unicall"):
        print(issue.number, issue.title)  # follows every page on its own
```

```python
from emissary.examples.stripe_client import StripeClient, NewCustomer

async with StripeClient(secret_key="sk_test_...") as stripe:
    customer = await stripe.create_customer(NewCustomer(email="a@example.com"))
    # form-encoded on the wire, idempotency key attached automatically --
    # neither is visible here
```

## Transport and retries

`Transport` wraps an `httpx.AsyncClient`; `RetryPolicy` decides what gets
retried, how long to wait, and whether a given call is even allowed to
retry at all.

1. **`Retry-After` has two legal shapes.** RFC 9110 allows a delay in
   seconds or an HTTP-date, and a server can send either. `parse_retry_after`
   handles both and returns `None` for anything else, rather than guessing.
   [`test_retry_after_parsing.py`](tests/test_retry_after_parsing.py)
2. **Retrying a POST can duplicate it.** `idempotent_only=True` is the
   default: GET/PUT/DELETE retry on `RetryPolicy`'s status list, POST/PATCH
   don't unless told otherwise — because a POST that already reached the
   server can create the same thing twice.
   [`test_transport.py`](tests/test_transport.py)

## Auth

`BearerTokenAuth`, `ApiKeyAuth`, and `OAuth2ClientCredentialsAuth`, all
built on `httpx.Auth` directly rather than a parallel mechanism for
attaching headers and reacting to a 401.

3. **A stampede on token refresh.** Every concurrent request holding the
   same expired token sees its own 401 and independently decides to
   refresh — N calls to the token endpoint for one actual expiry. The
   refresh goes through [`unicall`](https://github.com/i-safonoff/unicall),
   this author's own singleflight library, so concurrent refreshes share
   one call. [`test_concurrent_401s_share_one_token_refresh`](tests/test_auth.py)

## Endpoints as objects

`@endpoint(method, path)` turns a method into a request: path placeholders
from same-named parameters, a `BaseModel` parameter as the JSON (or form)
body, the return annotation as what the response becomes.

4. **A path parameter can smuggle a slash.** `quote(..., safe="")` before
   it goes into the URL, or a value containing `/` could route into a
   different endpoint entirely. Verifying it needed the raw wire bytes, not
   `request.path` — the test server's own WSGI layer decodes `%2F` back to
   `/` before a handler ever sees it, so the two are already
   indistinguishable by the time you'd think to check.
   [`test_path_params_are_url_escaped`](tests/test_endpoint.py)
5. **An idempotency key must survive every retry of the same call, not get
   reissued per attempt.** Generated once, before `Transport`'s retry loop
   starts. A fresh key on every attempt would mean the server sees N
   different requests instead of N attempts at the same one — defeating
   the entire mechanism it exists for.
   [`test_idempotency_key_stays_the_same_across_retries`](tests/test_endpoint.py)

## Pagination

`PaginationStrategy` is two methods — `items(response)` and
`next_url(response)` — with three implementations against real shapes:
`LinkHeaderPagination` (GitHub, via `httpx`'s own RFC 8288 parser),
`CursorPagination` (Stripe's `has_more`), `OffsetPagination`.

6. **A cyclic next-link would loop forever.** Found the hard way: the first
   version of the Link-header test hung on its own first run, because an
   unconstrained `expect_request` matcher shadowed the paginated one and
   every request landed on a handler whose `Link` header pointed at itself.
   That's not just a fixture mistake — a genuinely broken API could produce
   the same shape — so `@endpoint(paginate=...)` now tracks fetched URLs
   and raises `PaginationLoopError` on a repeat instead of streaming
   requests forever. [`test_a_cyclic_next_link_raises_instead_of_looping_forever`](tests/test_pagination.py)

## Proving it against real APIs

`GitHubClient` and `StripeClient` in [`examples/`](examples/) are the
payoff: everything above, used against two APIs this project didn't design
and can't adjust to fit, tested against real (GitHub) and documented
(Stripe) response shapes rather than invented ones.

7. **Not every API is JSON.** Stripe's v1 API is
   `application/x-www-form-urlencoded`, nested objects as bracket-notation
   keys (`metadata[key]=value`). Found building the client, not planned for
   in advance — `@endpoint(..., body_encoding="form")` and a small
   recursive flattener were both added afterward.
   [`test_body_encoding_form_sends_flattened_form_data`](tests/test_endpoint.py)
8. **Every API shapes its errors differently.** GitHub: `{"message": ...}`.
   Stripe: `{"error": {"message": ...}}`. `ErrorMapper` is one method,
   `JsonFieldErrorMapper` covers both with a dot-separated field path
   instead of a new class per API.
   [`test_a_nested_field_message_is_appended_to_the_exception`](tests/test_errors.py)
9. **`async with SomeClient() as client` had lost `client`'s own type.**
   `ApiClient.__aenter__` returned the literal base class instead of
   `Self`, so every `@endpoint` method a subclass added disappeared from
   mypy's view the moment the client was used as a context manager — the
   normal way to use one. Found by running mypy on the GitHub client's own
   tests, not by hand.
   [`docs/DECISIONS.md`](docs/DECISIONS.md#9-apiclient-uses-self-not-the-literal-class-name)

## The branches

| Branch | | |
|---|---|---|
| [`feat/endpoints`](../../tree/feat/endpoints) | merged | `@endpoint`, `ApiClient`, problems 4–5 |
| [`feat/pagination`](../../tree/feat/pagination) | merged | `PaginationStrategy` and its three shapes, problem 6 |
| [`feat/error-mapper`](../../tree/feat/error-mapper) | merged | `ErrorMapper`, problem 8 |
| [`feat/github-client`](../../tree/feat/github-client) | merged | `GitHubClient`, the `Self` fix (problem 9) |
| [`feat/stripe-client`](../../tree/feat/stripe-client) | merged | `StripeClient`, `body_encoding="form"` (problem 7) |

Transport, retries, and auth (problems 1–3) landed straight on `main` —
before the branch-per-feature habit from this author's other projects
picked back up here.

## Quickstart

```bash
git clone https://github.com/i-safonoff/emissary.git
cd emissary
pip install -e ".[dev]"
```

```python
import asyncio
from pydantic import BaseModel
from emissary import ApiClient, endpoint

class Fact(BaseModel):
    fact: str

class CatFactsClient(ApiClient):
    base_url = "https://catfact.ninja"

    @endpoint("GET", "/fact")
    async def random_fact(self) -> Fact: ...

async def main() -> None:
    async with CatFactsClient() as client:
        fact = await client.random_fact()
        print(fact.fact)

asyncio.run(main())
```

Or the real ones, with credentials of your own:

```bash
python -c "
import asyncio
from emissary.examples.github_client import GitHubClient

async def main():
    async with GitHubClient(token='ghp_...') as gh:
        print(await gh.get_repo('i-safonoff', 'emissary'))

asyncio.run(main())
"
```

## Testing it

```bash
pytest
```

Every test drives a real local HTTP server (`pytest-httpserver`) rather
than mocking `httpx` — the same conviction as this author's other
projects: a mock would have let the path-escaping bug (problem 4) and the
pagination loop (problem 6) both pass silently, since both depend on
exactly how a real server and a real WSGI stack behave, not on what a
client library assumes about them. The GitHub and Stripe client tests
extend this the same way, serving real (GitHub) or documented (Stripe)
response bodies locally instead of hitting either API live in CI.

## Project layout

```
src/emissary/
├── __init__.py         the public API
├── _transport.py        retry loop, per-call override
├── _retry.py            RetryPolicy, Retry-After parsing
├── _exceptions.py        the status-code exception hierarchy
├── _errors.py            ErrorMapper, JsonFieldErrorMapper
├── _auth.py              BearerTokenAuth, ApiKeyAuth, OAuth2ClientCredentialsAuth
├── _client.py            ApiClient
├── _endpoint.py          @endpoint -- path, body, idempotency, pagination
├── _pagination.py        PaginationStrategy and its three shapes
└── _forms.py             Stripe-style form flattening

examples/
├── github_client.py      Bearer auth, Link-header pagination, JSON
└── stripe_client.py       Bearer-over-secret-key, cursor pagination, form bodies

tests/                    52 tests against a real local HTTP server
tests/examples/            4 tests against real/documented API response shapes
docs/DECISIONS.md          nine decisions, with what each gave up
```

## What I would do differently at scale

Honest limitations, not a roadmap:

- **No live-credential tests.** GitHub's fixtures are real captured
  responses; Stripe's are Stripe's own documented examples. Neither suite
  ever calls a live API, so a real breaking change on either side (a
  renamed field, a changed error shape) would not be caught until it broke
  in production, not in CI.
- **`body_encoding` is binary.** JSON or form, chosen once per endpoint.
  An API that mixes both, or needs multipart, isn't served by either.
- **One `Idempotency-Key` convention.** Header name and value shape (a
  UUID4) match Stripe's and are a reasonable default elsewhere, but an API
  with a different idempotency contract (a client-supplied sequence
  number, say) would need its own mechanism, not a parameter on this one.
- **No request/response logging or tracing hooks.** Debugging a real
  integration wants to see the request that actually went out, headers and
  all; nothing here exposes that short of reading `Transport`'s httpx
  client directly.
- **Pagination assumes a single sequential cursor.** None of the three
  strategies handle an API that pages by parallel cursors (per-shard, say)
  or offers no way to resume from a partial failure mid-page.

## License

MIT — see [LICENSE](LICENSE).
