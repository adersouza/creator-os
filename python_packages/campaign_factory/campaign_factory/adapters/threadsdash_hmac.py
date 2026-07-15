"""Shared signing helpers for Campaign Factory -> ThreadsDashboard requests."""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_VERSION = "v1"


def sign_body(body: bytes, *, secret: str, timestamp: str, nonce: str) -> str:
    """Return the exact HMAC header value used by ThreadsDashboard."""
    if not secret:
        raise ValueError("Campaign Factory ingest secret is required")
    signing_input = (
        timestamp.encode("ascii") + b"." + nonce.encode("ascii") + b"." + body
    )
    digest = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_VERSION}={digest}"


def signed_headers(
    body: bytes, *, secret: str, timestamp: str, nonce: str
) -> dict[str, str]:
    return {
        "X-Campaign-Factory-Signature": sign_body(
            body, secret=secret, timestamp=timestamp, nonce=nonce
        ),
        "X-Campaign-Factory-Timestamp": timestamp,
        "X-Campaign-Factory-Nonce": nonce,
    }
