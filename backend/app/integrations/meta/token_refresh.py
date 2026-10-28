import logging

import httpx

from app.integrations.meta.errors import MetaAPIError
from app.integrations.meta.oauth import _raise_meta_error

logger = logging.getLogger(__name__)

# Refreshes a long-lived Instagram User access token (Instagram Login).
# Verified against https://developers.facebook.com/documentation/instagram-platform/reference/refresh_access_token
# The token must be long-lived, at least 24 hours old, unexpired and carry
# instagram_business_basic. The refreshed token is valid for 60 days.
META_REFRESH_TOKEN_URL = "https://graph.instagram.com/refresh_access_token"


def refresh_long_lived_token(access_token: str) -> dict:
    """Sync (Celery-side) refresh. Returns {"access_token", "token_type", "expires_in"}."""
    logger.info("Refreshing Instagram long-lived token")
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                META_REFRESH_TOKEN_URL,
                params={"grant_type": "ig_refresh_token", "access_token": access_token},
            )
    except httpx.HTTPError as exc:
        # Type only: the request URL carries the token, so never str(exc).
        raise MetaAPIError(f"Instagram token refresh request failed: {type(exc).__name__}")
    try:
        data = response.json()
    except Exception:
        raise MetaAPIError("Invalid JSON response from Instagram", status_code=response.status_code)
    if response.status_code >= 400 or "error" in data or "error_type" in data:
        _raise_meta_error(response, data, "Instagram token refresh failed")
    if "access_token" not in data:
        raise MetaAPIError(
            "No access_token in Instagram token refresh response",
            status_code=response.status_code,
            response_body=data,
        )
    return data
