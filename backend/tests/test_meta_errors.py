import pytest

from app.integrations.meta.errors import classify_meta_error, ErrorClassification


def test_classify_retryable_500():
    result = classify_meta_error(500, {"error": {"message": "Internal server error"}})
    assert result.category == "retryable"
    assert result.retryable is True


def test_classify_retryable_429():
    result = classify_meta_error(429, {"error": {"message": "Rate limit"}})
    assert result.category == "retryable"
    assert result.retryable is True


def test_classify_token_error():
    result = classify_meta_error(400, {"error": {"message": "Invalid token", "code": 190}})
    assert result.category == "token_error"
    assert result.retryable is False


def test_classify_permission_error():
    result = classify_meta_error(403, {"error": {"message": "Insufficient permission", "code": 200}})
    assert result.category == "permission_error"
    assert result.retryable is False


def test_classify_expired_private_reply():
    result = classify_meta_error(400, {"error": {"message": "Private reply expired", "error_subcode": 2018278}})
    assert result.category == "expired_private_reply"
    assert result.retryable is False


def test_classify_policy_error():
    result = classify_meta_error(400, {"error": {"message": "Policy violation detected"}})
    assert result.category == "policy_error"
    assert result.retryable is False


def test_classify_user_unreachable():
    result = classify_meta_error(400, {"error": {"message": "User is not available"}})
    assert result.category == "user_unreachable"
    assert result.retryable is False


def test_classify_invalid_reference():
    result = classify_meta_error(404, {"error": {"message": "Comment does not exist"}})
    assert result.category == "invalid_reference"
    assert result.retryable is False


def test_classify_unrecognized_error_is_retried_not_dropped():
    result = classify_meta_error(400, {"error": {"message": "Something weird", "code": 99999}})
    assert result.category == "unclassified"
    assert result.retryable is True


def test_classify_non_english_error_message_is_retried_not_dropped():
    # Regression: keyword classification is English-only, so a localized
    # Meta error message (e.g. French) must not be silently treated as a
    # permanent failure just because none of the English keyword lists match.
    result = classify_meta_error(400, {"error": {"message": "L'utilisateur demandé est introuvable.", "code": 100}})
    assert result.category == "unclassified"
    assert result.retryable is True
