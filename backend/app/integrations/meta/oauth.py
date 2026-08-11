import logging

import httpx

from app.core.config import settings
from app.integrations.meta.errors import MetaAPIError

logger = logging.getLogger(__name__)

# Instagram API with Instagram Login (Business Login for Instagram) endpoints.
# Verified against https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login
META_OAUTH_BASE = "https://www.instagram.com/oauth/authorize"
META_TOKEN_EXCHANGE_URL = "https://api.instagram.com/oauth/access_token"
META_LONG_LIVED_TOKEN_URL = "https://graph.instagram.com/access_token"


def build_oauth_url(state: str) -> str:
    redirect_uri = f"{settings.APP_BASE_URL}/meta/connect/callback"
    url = (
        f"{META_OAUTH_BASE}"
        f"?client_id={settings.META_APP_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=instagram_business_basic,instagram_business_manage_messages,instagram_business_manage_comments"
        f"&state={state}"
        f"&response_type=code"
    )
    return url


def _raise_meta_error(response: httpx.Response, data: dict, fallback: str) -> None:
    """Normalize Instagram error shapes into MetaAPIError.

    api.instagram.com rejects with {"error_type", "code", "error_message"};
    graph.instagram.com rejects with {"error": {"message", ...}}.
    """
    error = data.get("error")
    if isinstance(error, dict):
        msg = error.get("message") or fallback
    else:
        msg = data.get("error_message") or data.get("error_description") or fallback
    raise MetaAPIError(msg, status_code=response.status_code, response_body=data)


async def exchange_code_for_short_lived_token(code: str, redirect_uri: str) -> dict:
    logger.info("Exchanging code for short-lived token")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            META_TOKEN_EXCHANGE_URL,
            data={
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
    try:
        data = response.json()
    except Exception:
        raise MetaAPIError("Invalid JSON response from Instagram", status_code=response.status_code)
    if response.status_code >= 400 or "error" in data or "error_type" in data:
        _raise_meta_error(response, data, "Instagram OAuth error")
    # Instagram Login wraps the token in a data array per the docs; some
    # responses return the token at the top level. Normalize both.
    if "access_token" in data:
        return data
    data_list = data.get("data")
    if isinstance(data_list, list) and data_list and "access_token" in data_list[0]:
        return data_list[0]
    raise MetaAPIError(
        "No access_token in Instagram token response",
        status_code=response.status_code,
        response_body=data,
    )


async def exchange_for_long_lived_token(short_lived_token: str) -> dict:
    logger.info("Exchanging short-lived token for long-lived token")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            META_LONG_LIVED_TOKEN_URL,
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": settings.META_APP_SECRET,
                "access_token": short_lived_token,
            },
        )
    try:
        data = response.json()
    except Exception:
        raise MetaAPIError("Invalid JSON response from Instagram", status_code=response.status_code)
    if response.status_code >= 400 or "error" in data or "error_type" in data:
        _raise_meta_error(response, data, "Instagram long-lived token error")
    if "access_token" not in data:
        raise MetaAPIError(
            "No access_token in Instagram long-lived token response",
            status_code=response.status_code,
            response_body=data,
        )
    return data
