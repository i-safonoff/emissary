# Decisions

Context, decision, cost. The cost column is the point: a decision recorded
without what it gave up is one nobody can revisit.

---

## 1. `Retry-After` is parsed, not assumed to be seconds

**Context.** RFC 9110 10.2.3 allows a server to answer `Retry-After` with
either an integer number of seconds or an HTTP-date.

**Decision.** `parse_retry_after` tries an integer first, then an
HTTP-date, and returns `None` — falling back to computed backoff — for
anything that's neither.

**Cost.** A header this library can't parse is treated as if it weren't
there at all, rather than guessed at. The alternative — assuming
delay-seconds always — works until the first API that sends a date, and
then waits the wrong amount of time silently.

---

## 2. `idempotent_only` defaults to `True`

**Context.** `RetryPolicy` needs to decide which HTTP methods are safe to
retry on a transient failure.

**Decision.** GET/PUT/DELETE retry by `RetryPolicy`'s own status list;
POST/PATCH don't, unless a caller opts in per-policy or per-endpoint.

**Cost.** A POST that would have been safe to retry (idempotent by the
API's own contract, just not by HTTP's) doesn't retry by default and the
caller pays for a failure that a retry could have absorbed. The
alternative — retrying POST by default — risks creating the same resource
twice on an API with no idempotency contract at all, which is a worse
failure than one avoidable error.

---

## 3. OAuth2 token refresh goes through `unicall`

**Context.** Every concurrent request holding an expired token
independently sees a 401 and independently decides to refresh.

**Decision.** `OAuth2ClientCredentialsAuth._fetch_token` is wrapped in
`unicall()` — this author's own singleflight library — so concurrent
refreshes collapse into one.

**Cost.** A second, external dependency for a single method call, and a
maintenance link between two projects: a change to `unicall`'s decorator
surface is now something this project has to notice, not just Stripe's or
GitHub's API. Writing this coalescing by hand instead would have been a
few dozen lines and no dependency — the trade taken here is that those few
dozen lines are exactly the kind of thing `unicall` already has tests for
and this project doesn't need to re-derive.

---

## 4. Path parameters are URL-escaped through `quote(..., safe="")`

**Context.** A path placeholder's value comes from a caller-supplied
argument, which could contain a `/`, a space, or anything else that means
something different once it's part of a URL.

**Decision.** Every path parameter goes through `urllib.parse.quote` with
no safe characters, including `/`, before it's substituted into the path
template.

**Cost.** A value that's supposed to already be a multi-segment path
(rare, but real for some APIs) gets each `/` escaped to `%2F` and arrives
at the server as one segment, not several — the caller has to build that
case as a literal part of the path template instead of a parameter. The
alternative, not escaping `/`, means a parameter value can silently route
a request to a different endpoint than the one that was called.

---

## 5. An idempotency key is minted once, before the retry loop

**Context.** `idempotent=False` attaches an `Idempotency-Key` header so a
retried write is recognized as a repeat, not a new request.

**Decision.** The key is generated a single time, before `Transport`'s
retry loop starts, and carried unchanged on every attempt of that call.

**Cost.** None, really — the alternative (a fresh key per attempt) doesn't
trade anything for anything; it just defeats the entire mechanism, since
the server would see N distinct requests instead of N attempts at the
same one. Recorded anyway because it's exactly the kind of one-line change
("regenerate the key each time, for freshness") that looks harmless and
silently breaks the feature.

---

## 6. Pagination tracks fetched URLs and raises on a repeat

**Context.** A next-page link that points back at a URL already fetched —
broken pagination logic on the API's side, or actively hostile — would
otherwise stream requests forever with nothing to stop it.

**Decision.** `@endpoint(paginate=...)` keeps a `set` of every URL fetched
so far in that call and raises `PaginationLoopError` the moment a URL
repeats.

**Cost.** One string per page, held for the lifetime of the generator —
irrelevant for any pagination a person would actually wait through, and
the failure mode it replaces (memory and request volume with no upper
bound) is worse by any measure. A page-count cap was the other option
considered and rejected: it needs a number tuned per API, and it would
still let a short cycle spin many times before tripping instead of
catching it on the second occurrence.

---

## 7. `body_encoding` is an explicit choice, not sniffed from the API

**Context.** GitHub's API takes JSON bodies; Stripe's v1 API takes
`application/x-www-form-urlencoded`. Nothing about a URL or a method says
which.

**Decision.** `@endpoint(..., body_encoding="form")` — a per-endpoint
opt-in, defaulting to `"json"` — rather than trying to detect the right
encoding from a response header or a prior request.

**Cost.** Every endpoint definition has to know its own API's convention
up front; there's no "try JSON, fall back to form" magic. Deliberate: an
API that silently accepted both would make this unnecessary, and one that
accepted neither the client guessed would fail in a way that's harder to
diagnose than a wrong parameter to `@endpoint`.

---

## 8. `ErrorMapper` is a `Protocol`, and `JsonFieldErrorMapper` is the only implementation shipped

**Context.** GitHub's error body is `{"message": ...}`; Stripe's is
`{"error": {"message": ...}}`. Every API is different enough that no
single default is right more often than it's wrong.

**Decision.** One method, `message_for(response) -> str | None`.
`JsonFieldErrorMapper` covers the common case — a string at a
dot-separated JSON path — rather than shipping a mapper per known API.

**Cost.** An API whose error message isn't a flat string at a fixed path
(computed from multiple fields, or from a non-JSON body) needs its own
`ErrorMapper` implementation; `JsonFieldErrorMapper` won't stretch to fit
it. That's the intended boundary — a helper for the common shape, not an
attempt to cover every error format that exists.

---

## 9. `ApiClient` uses `Self`, not the literal class name

**Context.** `async with SomeClient(...) as client:` needs `client` typed
as `SomeClient`, with every `@endpoint` method that subclass added, not as
the base `ApiClient`.

**Decision.** `ApiClient.__aenter__` returns `typing.Self`. Found as a
real mypy failure on the GitHub client's own tests — `client.get_repo(...)`
reported as "ApiClient has no attribute get_repo" — not written correctly
the first time.

**Cost.** `Self` needs Python 3.11; this project supports 3.10. Imported
under `TYPE_CHECKING` from `typing_extensions` instead, which costs
nothing at runtime (the annotation is already lazily evaluated via
`from __future__ import annotations`) but does add `typing_extensions` as
an explicit dev dependency rather than trusting it to keep arriving
transitively through pydantic or httpx.
