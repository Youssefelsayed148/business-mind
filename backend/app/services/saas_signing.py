"""HMAC signing for the Many <-> SaaS channel contract (section 3).

Signature: `sha256=` + hex HMAC-SHA256(secret, timestamp + "." + raw_body).
Everything is computed over bytes; comparison is constant-time.
"""

import hashlib
import hmac
import time

HEADER_CONNECTION = "X-Osiris-Connection"
HEADER_TIMESTAMP = "X-Osiris-Timestamp"
HEADER_SIGNATURE = "X-Osiris-Signature"
MAX_SKEW_SECONDS = 300
MAX_BODY_BYTES = 64 * 1024
_PREFIX = "sha256="


def compute_signature(secret: str, timestamp: str, body: bytes) -> str:
    mac = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256)
    return _PREFIX + mac.hexdigest()


def sign_headers(connection_id: str, secret: str, body: bytes, *, now: float | None = None) -> dict[str, str]:
    timestamp = str(int(now if now is not None else time.time()))
    return {
        HEADER_CONNECTION: connection_id,
        HEADER_TIMESTAMP: timestamp,
        HEADER_SIGNATURE: compute_signature(secret, timestamp, body),
    }


def verify_signature(
    secrets: list[str],
    timestamp: str | None,
    signature: str | None,
    body: bytes,
    *,
    now: float | None = None,
) -> bool:
    """True if the timestamp is within 5 minutes of now and the signature
    matches any of `secrets` (current plus, during rotation, previous). The
    caller returns one generic 401 for every False."""
    if not timestamp or not signature or len(body) > MAX_BODY_BYTES:
        return False
    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    current = now if now is not None else time.time()
    if abs(current - sent_at) > MAX_SKEW_SECONDS:
        return False
    given = signature.encode("utf-8", errors="replace")
    matched = False
    # No early exit: every candidate secret is always compared.
    for secret in secrets:
        expected = compute_signature(secret, str(sent_at), body).encode("ascii")
        if hmac.compare_digest(expected, given):
            matched = True
    return matched
