from dataclasses import dataclass


class MetaAPIError(Exception):
    """Raised when the Meta Graph API returns an error response."""

    def __init__(self, message: str, status_code: int | None = None, response_body: dict | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}


class MetaOAuthError(MetaAPIError):
    """Raised for OAuth-specific errors (code exchange, token refresh).

    Semantic subclass of MetaAPIError so callers can catch OAuth errors
    separately from general Graph API errors without changing behaviour.
    """


@dataclass
class ErrorClassification:
    category: str  # e.g. retryable, token_error, permission_error, etc.
    retryable: bool
    description: str


def classify_meta_error(status_code: int, response_json: dict) -> ErrorClassification:
    """Classify a Meta API error response into actionable categories."""

    error = response_json.get("error", {})
    error_code = error.get("code", 0)
    error_subcode = error.get("error_subcode", 0)
    error_msg = error.get("message", "").lower()

    # HTTP-level retryable
    if status_code >= 500:
        return ErrorClassification("retryable", True, f"HTTP {status_code} server error")
    if status_code == 429:
        return ErrorClassification("retryable", True, "Rate limit hit (HTTP 429)")

    # Token errors
    token_keywords = ["invalid token", "expired token", "session has expired", "access token", "auth"]
    if any(kw in error_msg for kw in token_keywords) or error_code in [190, 102]:
        return ErrorClassification("token_error", False, "Invalid or expired access token")

    # Permission errors
    permission_keywords = ["permission", "not authorized", "denied", "insufficient permission"]
    if any(kw in error_msg for kw in permission_keywords) or error_code in [200, 10]:
        return ErrorClassification("permission_error", False, "Missing permission for this action")

    # Policy errors
    policy_keywords = ["policy", "violation", "spam", "abuse"]
    if any(kw in error_msg for kw in policy_keywords):
        return ErrorClassification("policy_error", False, "Meta policy violation")

    # Expired private reply / comment too old
    expired_keywords = ["expired", "too old", "cannot reply", "private reply"]
    if any(kw in error_msg for kw in expired_keywords) or error_subcode in [2018278, 2018034]:
        return ErrorClassification("expired_private_reply", False, "Private reply window expired or comment too old")

    # User unreachable
    unreachable_keywords = ["cannot message", "unreachable", "not available", "deleted"]
    if any(kw in error_msg for kw in unreachable_keywords):
        return ErrorClassification("user_unreachable", False, "Recipient is unreachable")

    # Invalid reference (comment_id/media_id)
    invalid_ref_keywords = ["invalid", "does not exist", "not found", "cannot be found"]
    if any(kw in error_msg for kw in invalid_ref_keywords) and status_code in [400, 404]:
        return ErrorClassification("invalid_reference", False, "Invalid comment or media reference")

    return ErrorClassification("unknown_non_retryable", False, f"Unclassified error (HTTP {status_code}, code {error_code})")
