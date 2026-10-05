"""WhatsApp-only identifier normalization and safe log rendering."""

from __future__ import annotations

import re


_NON_DIGITS = re.compile(r"\D+")


def normalize_wa_id(value: object) -> str | None:
    """Return a digits-only WA ID when it has Meta's supported length."""
    digits = _NON_DIGITS.sub("", str(value or ""))
    return digits if 6 <= len(digits) <= 20 else None


def mask_wa_id(value: object) -> str:
    """Mask a WA ID for logs, retaining at most its final four digits."""
    digits = _NON_DIGITS.sub("", str(value or ""))
    if not digits:
        return "<invalid>"
    return f"***{digits[-4:]}"
