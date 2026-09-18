from __future__ import annotations

import hashlib
import hmac
import time


class WebhookVerificationError(Exception):
    """Raised when a webhook payload's signature doesn't verify -- wrong
    secret, a tampered payload, or (for schemes with a timestamp) too old.

    Raised, not returned as a bool: a caller that forgets to check a
    return value is a caller that silently accepts a forged payload, and
    that failure mode doesn't exist if there's no return value to ignore.
    """


def verify_github_signature(payload: bytes, signature_header: str, secret: str) -> None:
    """Verifies GitHub's `X-Hub-Signature-256` header:
    `sha256=<hex HMAC-SHA256 of the raw request body>`.

    `payload` must be the exact bytes GitHub sent -- not a JSON object
    parsed and re-serialized. Re-dumping changes whitespace and can
    reorder keys, which changes the bytes the signature was computed over
    even though the *data* is unchanged, and the signature stops matching
    for a reason that has nothing to do with tampering.
    """
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        raise WebhookVerificationError(f"unexpected signature format: {signature_header!r}")
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    provided = signature_header[len(prefix) :]
    if not hmac.compare_digest(expected, provided):
        raise WebhookVerificationError("signature does not match")


def verify_stripe_signature(
    payload: bytes,
    signature_header: str,
    secret: str,
    *,
    tolerance_seconds: float = 300,
) -> None:
    """Verifies Stripe's `Stripe-Signature` header:
    `t=<timestamp>,v1=<hex HMAC-SHA256 of "{timestamp}.{payload}">`
    (a `v0=` legacy signature may also be present and is ignored).

    Also checks the timestamp is recent. The signature alone can't tell a
    fresh webhook from a captured-and-replayed one -- both have a valid
    signature, since neither the payload nor the secret changed. The
    timestamp is what makes a replay eventually stop working.
    """
    parts = dict(item.split("=", 1) for item in signature_header.split(",") if "=" in item)
    timestamp = parts.get("t")
    signature = parts.get("v1")
    if timestamp is None or signature is None:
        raise WebhookVerificationError(f"malformed Stripe-Signature header: {signature_header!r}")

    signed_payload = f"{timestamp}.".encode() + payload
    expected = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise WebhookVerificationError("signature does not match")

    try:
        age = time.time() - float(timestamp)
    except ValueError:
        raise WebhookVerificationError(f"non-numeric timestamp: {timestamp!r}") from None
    if age > tolerance_seconds:
        raise WebhookVerificationError(
            f"timestamp is {age:.0f}s old, older than the {tolerance_seconds:.0f}s tolerance"
        )
