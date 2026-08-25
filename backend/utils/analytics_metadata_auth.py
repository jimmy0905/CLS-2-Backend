"""Authentication helpers for the private Cube metadata compiler endpoint."""
from __future__ import annotations

import hashlib
import hmac
import time


def sign_metadata_request(secret: str, profile: str, timestamp: int) -> str:
    message = f"{int(timestamp)}:{profile}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_metadata_signature(
    secret: str,
    profile: str,
    timestamp: str,
    signature: str,
    *,
    now: int | None = None,
    max_clock_skew_seconds: int = 300,
) -> bool:
    if not secret or not signature:
        return False
    try:
        issued_at = int(timestamp)
    except (TypeError, ValueError):
        return False
    current_time = int(time.time()) if now is None else int(now)
    if abs(current_time - issued_at) > max_clock_skew_seconds:
        return False
    expected = sign_metadata_request(secret, profile, issued_at)
    return hmac.compare_digest(expected, signature)
