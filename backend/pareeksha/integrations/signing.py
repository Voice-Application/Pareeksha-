"""Stripe-style HMAC signing for the Generic Webhook, both directions (docs/10 section 2.1).

    X-Pareeksha-Timestamp: <unix seconds>
    X-Pareeksha-Signature: v1=<hex(hmac_sha256(secret, f"{timestamp}.{raw_body}"))>[,v1=<hex>]

Receivers reject timestamps older than 5 minutes (and too far in the future) and compare in
constant time. During secret rotation two signatures may be present and either may match.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Iterable, Mapping

TIMESTAMP_HEADER = "X-Pareeksha-Timestamp"
SIGNATURE_HEADER = "X-Pareeksha-Signature"
TOLERANCE_S = 300


class SignatureError(Exception):
    """Inbound signature missing, malformed, stale or wrong."""


class StaleTimestampError(SignatureError):
    """The timestamp is outside the replay window (HTTP 408 on the inbound endpoint)."""


def compute_signature(secret: str, timestamp: int | str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return mac.hexdigest()


def sign_headers(
    secrets: str | Iterable[str], body: bytes, *, timestamp: int | None = None
) -> dict[str, str]:
    """Headers for an outbound request; pass two secrets while rotating."""
    ts = int(time.time()) if timestamp is None else timestamp
    secret_list = [secrets] if isinstance(secrets, str) else list(secrets)
    if not secret_list:
        raise ValueError("at least one signing secret is required")
    value = ",".join(f"v1={compute_signature(s, ts, body)}" for s in secret_list)
    return {TIMESTAMP_HEADER: str(ts), SIGNATURE_HEADER: value}


def verify_signature(
    headers: Mapping[str, str],
    body: bytes,
    secrets: str | Iterable[str],
    *,
    now: float | None = None,
    tolerance_s: int = TOLERANCE_S,
) -> None:
    """Raise ``SignatureError`` unless a ``v1`` signature matches one of the active secrets."""
    lowered = {k.lower(): v for k, v in headers.items()}
    ts_raw = lowered.get(TIMESTAMP_HEADER.lower())
    sig_raw = lowered.get(SIGNATURE_HEADER.lower())
    if not ts_raw or not sig_raw:
        raise SignatureError("missing signature headers")
    try:
        ts = int(ts_raw)
    except ValueError as exc:
        raise SignatureError("malformed timestamp") from exc
    current = time.time() if now is None else now
    if abs(current - ts) > tolerance_s:
        raise StaleTimestampError("timestamp outside the tolerance window")
    provided = [part.strip()[3:] for part in sig_raw.split(",") if part.strip().startswith("v1=")]
    if not provided:
        raise SignatureError("no v1 signature")
    secret_list = [secrets] if isinstance(secrets, str) else list(secrets)
    matched = False
    for secret in secret_list:
        expected = compute_signature(secret, ts, body)
        for candidate in provided:
            # no early exit: timing does not depend on which pair matches
            matched |= hmac.compare_digest(expected, candidate)
    if not matched:
        raise SignatureError("signature mismatch")
