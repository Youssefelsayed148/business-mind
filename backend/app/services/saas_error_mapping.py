"""Meta error code/subcode -> contract `error_code` (delta A3).

Mapped by numeric code and subcode only, never by message text (Meta
localises it). The table is the "starting table" of A3 and is NOT yet
verified against current Meta documentation - check each row before relying
on it in production.
"""

WINDOW_CLOSED = "window_closed"
TEMPLATE_REQUIRED = "template_required"
RECIPIENT_UNREACHABLE = "recipient_unreachable"
RATE_LIMITED = "rate_limited"
CHANNEL_DISCONNECTED = "channel_disconnected"
MESSAGE_TOO_LONG = "message_too_long"
UNKNOWN = "unknown"

_WHATSAPP = {
    131047: WINDOW_CLOSED,
    131026: RECIPIENT_UNREACHABLE,
    130429: RATE_LIMITED,
    131056: RATE_LIMITED,
    131058: TEMPLATE_REQUIRED,
    190: CHANNEL_DISCONNECTED,
}
_WHATSAPP.update({code: TEMPLATE_REQUIRED for code in range(132000, 132016)})

_MESSENGER_CODES = {
    4: RATE_LIMITED,
    17: RATE_LIMITED,
    32: RATE_LIMITED,
    613: RATE_LIMITED,
    190: CHANNEL_DISCONNECTED,
    102: CHANNEL_DISCONNECTED,
}


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


def error_detail(code, subcode=None, transport: str | None = None) -> str:
    """Short, personal-data-free detail for the status event (max 200)."""
    if transport:
        return f"send failed: {transport}"[:200]
    parts = [f"meta code {code}"] if code not in (None, "") else ["meta error"]
    if subcode not in (None, ""):
        parts.append(f"subcode {subcode}")
    return " ".join(parts)[:200]
