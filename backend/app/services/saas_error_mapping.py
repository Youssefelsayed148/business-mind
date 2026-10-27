"""Meta error code/subcode -> contract `error_code` (delta A3).

Mapped by numeric code and subcode only, never by message text (Meta
localises it). The table is the "starting table" of A3.

Verification (F-07, 2026-10): developers.facebook.com could not be fetched from
the build sandbox (DNS), so no row was checked by reading Meta's page in full.
Each row below says what it rests on:
  verified   = Meta's own error-code page, as quoted by a web-search snippet
  unverified = only third-party documentation, or no source found; confirm
               against https://developers.facebook.com/documentation/
               business-messaging/ (WhatsApp Cloud API and Messenger Platform
               "error codes") before relying on it.
Code 551 ("This person isn't available right now", subcode 1545041 in the
sources found) is NOT mapped: only third-party pages list it, Meta's page was
not confirmed to. It stays `unknown` until the owner verifies it.
"""

WINDOW_CLOSED = "window_closed"
TEMPLATE_REQUIRED = "template_required"
RECIPIENT_UNREACHABLE = "recipient_unreachable"
RATE_LIMITED = "rate_limited"
CHANNEL_DISCONNECTED = "channel_disconnected"
MESSAGE_TOO_LONG = "message_too_long"
UNKNOWN = "unknown"

_WHATSAPP = {
    131047: WINDOW_CLOSED,  # unverified: 24 h re-engagement window (third-party docs agree)
    131026: RECIPIENT_UNREACHABLE,  # unverified: message undeliverable (third-party docs agree)
    130429: RATE_LIMITED,  # unverified: Cloud API throughput limit (third-party docs agree)
    # unverified and disputed: most sources say pair (per-recipient) rate limit,
    # one lists a payment/eligibility problem. If it is the latter, retrying a
    # rate limit (see RATE_LIMIT_RETRY_DELAYS) is harmless but pointless.
    131056: RATE_LIMITED,
    131058: TEMPLATE_REQUIRED,  # unverified: no source found for this code
    190: CHANNEL_DISCONNECTED,  # unverified: invalid/expired access token
}
# unverified: 132000 (template parameter count mismatch) is confirmed by
# third-party docs; the rest of the 132000-132015 template range is unchecked.
_WHATSAPP.update({code: TEMPLATE_REQUIRED for code in range(132000, 132016)})

_MESSENGER_CODES = {
    4: RATE_LIMITED,  # verified: application request limit reached
    17: RATE_LIMITED,  # unverified: user-level request limit
    32: RATE_LIMITED,  # unverified: page-level request limit
    613: RATE_LIMITED,  # unverified: custom rate limit
    190: CHANNEL_DISCONNECTED,  # unverified: invalid/expired access token
    102: CHANNEL_DISCONNECTED,  # unverified: session/API session error
}
# Messenger / Instagram subcodes:
#   10 / 2534022 "sent outside of allowed window"  verified
#   2018278 (reported as code 10, "outside of allowed window")  unverified
#         (third-party docs only); kept as a subcode-only match on purpose
#   100 / 2018001 "No matching user found"  verified


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def map_meta_error(platform: str, code, subcode=None) -> str:
    code, subcode = _as_int(code), _as_int(subcode)
    if platform == "whatsapp":
        return _WHATSAPP.get(code, UNKNOWN)
    # Messenger (facebook) and Instagram share the Send API error model.
    if (code == 10 and subcode == 2534022) or subcode == 2018278:
        return WINDOW_CLOSED
    if code == 100 and subcode == 2018001:
        return RECIPIENT_UNREACHABLE
    return _MESSENGER_CODES.get(code, UNKNOWN)


def is_rate_limited(platform: str, code, subcode=None) -> bool:
    return map_meta_error(platform, code, subcode) == RATE_LIMITED


def error_detail(code, subcode=None, transport: str | None = None) -> str:
    """Short, personal-data-free detail for the status event (max 200)."""
    if transport:
        return f"send failed: {transport}"[:200]
    parts = [f"meta code {code}"] if code not in (None, "") else ["meta error"]
    if subcode not in (None, ""):
        parts.append(f"subcode {subcode}")
    return " ".join(parts)[:200]
