import pytest

from app.integrations.meta.whatsapp_ids import mask_wa_id, normalize_wa_id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("16315551234", "16315551234"), ("+1 (631) 555-1234", "16315551234"), ("123", None), ("", None), ("1" * 21, None), (None, None)],
)
def test_normalize_wa_id(raw, expected):
    assert normalize_wa_id(raw) == expected


def test_mask_wa_id_never_returns_full_number():
    assert mask_wa_id("+1 (631) 555-1234") == "***1234"
    assert mask_wa_id("bad") == "<invalid>"
