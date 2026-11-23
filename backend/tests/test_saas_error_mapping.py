"""M-04: Meta error code/subcode -> contract error_code (delta A3).

The bodies below follow the shape of Meta Graph API error responses
({"error": {"message", "type", "code", "error_subcode", "fbtrace_id"}}). They
are written from the A3 table, not captured from live traffic, and the table
itself is still unverified against Meta's current docs. Message text is
deliberately varied/localised to prove it is never consulted.
"""

import pytest

from app.services.saas_error_mapping import error_detail, map_meta_error

WA = "whatsapp"


def body(code, subcode=None, message="x"):
    err = {"message": message, "type": "OAuthException", "code": code, "fbtrace_id": "A1b2C3"}
    if subcode is not None:
        err["error_subcode"] = subcode
    return {"error": err}


def mapped(platform, response):
    err = response["error"]
    return map_meta_error(platform, err.get("code"), err.get("error_subcode"))


@pytest.mark.parametrize(
    "code,expected",
    [
        (131047, "window_closed"),
        (131026, "recipient_unreachable"),
        (130429, "rate_limited"),
        (131056, "rate_limited"),
        (131058, "template_required"),
        (132000, "template_required"),
        (132007, "template_required"),
        (132015, "template_required"),
        (190, "channel_disconnected"),
        (132016, "unknown"),
        (131031, "unknown"),
        (0, "unknown"),
    ],
)
def test_whatsapp_codes(code, expected):
    assert mapped(WA, body(code)) == expected


@pytest.mark.parametrize("platform", ["facebook", "instagram"])
@pytest.mark.parametrize(
    "response,expected",
    [
        (body(10, 2534022), "window_closed"),
        (body(100, 2018278), "window_closed"),
        (body(10, 2018278), "window_closed"),
        (body(100, 2018001), "recipient_unreachable"),
        (body(4), "rate_limited"),
        (body(17), "rate_limited"),
        (body(32), "rate_limited"),
        (body(613), "rate_limited"),
        (body(190), "channel_disconnected"),
        (body(190, 460), "channel_disconnected"),
        (body(102), "channel_disconnected"),
        (body(10), "unknown"),  # code 10 alone is a generic permission error
        (body(10, 1234567), "unknown"),
        (body(100), "unknown"),
        (body(100, 33), "unknown"),
        (body(2), "unknown"),
    ],
)
def test_messenger_and_instagram_codes(platform, response, expected):
    assert mapped(platform, response) == expected


def test_window_codes_do_not_apply_to_whatsapp_and_vice_versa():
    assert map_meta_error(WA, 10, 2534022) == "unknown"
    assert map_meta_error("facebook", 131047) == "unknown"


@pytest.mark.parametrize("text", ["Outside of allowed window", "خارج النافذة المسموح بها", "Fenêtre expirée", ""])
def test_message_text_is_never_consulted(text):
    assert mapped("facebook", body(10, 2534022, text)) == "window_closed"
    assert mapped("facebook", body(2, None, "outside of allowed window")) == "unknown"
    assert mapped(WA, body(131047, None, text)) == "window_closed"


def test_string_and_missing_codes_are_tolerated():
    assert map_meta_error(WA, "131047") == "window_closed"
    assert map_meta_error("facebook", "10", "2534022") == "window_closed"
    assert map_meta_error(WA, None) == "unknown"
    assert map_meta_error("instagram", "abc", "def") == "unknown"


def test_error_detail_has_only_codes_and_fits_the_limit():
    assert error_detail(131047) == "meta code 131047"
    assert error_detail(10, 2534022) == "meta code 10 subcode 2534022"
    assert error_detail(None) == "meta error"
    assert error_detail(None, None, "timeout") == "send failed: timeout"
    assert len(error_detail("9" * 500, "8" * 500)) <= 200
