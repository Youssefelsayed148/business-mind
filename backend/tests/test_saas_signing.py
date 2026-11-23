"""M-02: HMAC signing/verification (contract section 3)."""

import hashlib
import hmac

from app.services import saas_signing as signing

SECRET = "a" * 40
OTHER = "b" * 40
BODY = '{"event_id":"e1","text":"héllo"}'.encode("utf-8")
NOW = 1_800_000_000


def _headers(secret=SECRET, body=BODY, now=NOW):
    return signing.sign_headers("conn-1", secret, body, now=now)


def test_signature_format_matches_contract():
    headers = _headers()
    expected = hmac.new(SECRET.encode(), f"{NOW}.".encode() + BODY, hashlib.sha256).hexdigest()
    assert headers[signing.HEADER_SIGNATURE] == f"sha256={expected}"
    assert headers[signing.HEADER_TIMESTAMP] == str(NOW)
    assert headers[signing.HEADER_CONNECTION] == "conn-1"


def test_empty_body_signs_timestamp_and_dot():
    headers = signing.sign_headers("c", SECRET, b"", now=NOW)
    expected = hmac.new(SECRET.encode(), f"{NOW}.".encode(), hashlib.sha256).hexdigest()
    assert headers[signing.HEADER_SIGNATURE] == f"sha256={expected}"


def _verify(headers, secrets=(SECRET,), body=BODY, now=NOW):
    return signing.verify_signature(
        list(secrets), headers[signing.HEADER_TIMESTAMP], headers[signing.HEADER_SIGNATURE], body, now=now
    )


def test_valid_signature_accepted():
    assert _verify(_headers())


def test_rejection_matrix():
    good = _headers()
    assert not _verify(good, body=BODY + b" ")  # tampered body
    assert not _verify(_headers(secret=OTHER))  # wrong secret
    assert not _verify(good, now=NOW + 301)  # too old
    assert not _verify(good, now=NOW - 301)  # too far in the future
    assert _verify(good, now=NOW + 299)
    assert not signing.verify_signature([SECRET], None, good[signing.HEADER_SIGNATURE], BODY, now=NOW)
    assert not signing.verify_signature([SECRET], str(NOW), None, BODY, now=NOW)
    assert not signing.verify_signature([SECRET], "not-a-number", good[signing.HEADER_SIGNATURE], BODY, now=NOW)
    assert not signing.verify_signature([SECRET], str(NOW), "sha256=" + "0" * 64, BODY, now=NOW)
    assert not signing.verify_signature([SECRET], str(NOW), good[signing.HEADER_SIGNATURE][7:], BODY, now=NOW)
    assert not signing.verify_signature([], str(NOW), good[signing.HEADER_SIGNATURE], BODY, now=NOW)


def test_body_over_64kb_rejected():
    big = b"x" * (64 * 1024 + 1)
    headers = signing.sign_headers("c", SECRET, big, now=NOW)
    assert not _verify(headers, body=big)
    ok = b"x" * (64 * 1024)
    assert _verify(signing.sign_headers("c", SECRET, ok, now=NOW), body=ok)


def test_dual_secret_rotation_accepts_either():
    old = _headers(secret=OTHER)
    new = _headers(secret=SECRET)
    assert _verify(old, secrets=(SECRET, OTHER))
    assert _verify(new, secrets=(SECRET, OTHER))
    assert not _verify(old, secrets=(SECRET,))


def test_non_ascii_signature_header_does_not_raise():
    assert not signing.verify_signature([SECRET], str(NOW), "sha256=é" * 3, BODY, now=NOW)
