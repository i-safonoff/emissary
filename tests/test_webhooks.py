from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest

from emissary import (
    WebhookVerificationError,
    verify_github_signature,
    verify_stripe_signature,
)

SECRET = "whsec_test_secret"
PAYLOAD = b'{"type":"customer.created","id":"evt_123"}'


def _github_header(payload: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _stripe_header(payload: bytes, secret: str, timestamp: float) -> str:
    signed_payload = f"{timestamp:.0f}.".encode() + payload
    digest = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp:.0f},v1={digest}"


def test_github_signature_verifies_against_an_independently_computed_hmac() -> None:
    header = _github_header(PAYLOAD, SECRET)
    verify_github_signature(PAYLOAD, header, SECRET)  # raises on failure


def test_github_signature_rejects_a_tampered_payload() -> None:
    header = _github_header(PAYLOAD, SECRET)
    with pytest.raises(WebhookVerificationError, match="does not match"):
        verify_github_signature(PAYLOAD + b"tampered", header, SECRET)


def test_github_signature_rejects_the_wrong_secret() -> None:
    header = _github_header(PAYLOAD, SECRET)
    with pytest.raises(WebhookVerificationError):
        verify_github_signature(PAYLOAD, header, "wrong-secret")


def test_github_signature_rejects_a_malformed_header() -> None:
    with pytest.raises(WebhookVerificationError, match="unexpected signature format"):
        verify_github_signature(PAYLOAD, "sha1=deadbeef", SECRET)


def test_github_signature_over_a_reserialized_body_does_not_match() -> None:
    # The exact pitfall the docstring warns about: parsing JSON and
    # re-dumping it changes the bytes even when the data is unchanged, so
    # a signature computed over the original body no longer verifies.
    header = _github_header(PAYLOAD, SECRET)
    reserialized = json.dumps(json.loads(PAYLOAD)).encode()
    with pytest.raises(WebhookVerificationError):
        verify_github_signature(reserialized, header, SECRET)


def test_stripe_signature_verifies_against_an_independently_computed_hmac() -> None:
    header = _stripe_header(PAYLOAD, SECRET, time.time())
    verify_stripe_signature(PAYLOAD, header, SECRET)


def test_stripe_signature_rejects_a_tampered_payload() -> None:
    header = _stripe_header(PAYLOAD, SECRET, time.time())
    with pytest.raises(WebhookVerificationError, match="does not match"):
        verify_stripe_signature(PAYLOAD + b"tampered", header, SECRET)


def test_stripe_signature_rejects_an_old_timestamp() -> None:
    # A valid signature, computed over an old timestamp -- exactly what a
    # captured-and-replayed webhook looks like. The signature alone can't
    # tell the difference; the tolerance check is what catches it.
    old_timestamp = time.time() - 3600
    header = _stripe_header(PAYLOAD, SECRET, old_timestamp)
    with pytest.raises(WebhookVerificationError, match="tolerance"):
        verify_stripe_signature(PAYLOAD, header, SECRET, tolerance_seconds=300)


def test_stripe_signature_accepts_a_wider_tolerance_when_asked() -> None:
    old_timestamp = time.time() - 3600
    header = _stripe_header(PAYLOAD, SECRET, old_timestamp)
    verify_stripe_signature(PAYLOAD, header, SECRET, tolerance_seconds=7200)


def test_stripe_signature_rejects_a_malformed_header() -> None:
    with pytest.raises(WebhookVerificationError, match="malformed"):
        verify_stripe_signature(PAYLOAD, "not-a-valid-header", SECRET)


def test_stripe_signature_ignores_an_unrelated_v0_field() -> None:
    header = _stripe_header(PAYLOAD, SECRET, time.time())
    header_with_legacy = header + ",v0=some-legacy-sha1-signature"
    verify_stripe_signature(PAYLOAD, header_with_legacy, SECRET)
