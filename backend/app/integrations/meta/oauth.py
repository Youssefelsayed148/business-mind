import logging

import httpx

from app.core.config import settings
from app.integrations.meta.errors import MetaAPIError

logger = logging.getLogger(__name__)

META_OAUTH_BASE = "https://www.facebook.com/v21.0/dialog/oauth"
META_TOKEN_EXCHANGE_URL = "https://graph.facebook.com/v21.0/oauth/access_token"


def build_oauth_url(state: str) -> str:
    redirect_uri = f"{settings.APP_BASE_URL}/meta/connect/callback"
    url = (
        f"{META_OAUTH_BASE}"
        f"?client_id={settings.META_APP_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=instagram_business_basic,instagram_business_manage_messages,instagram_business_manage_comments,pages_show_list"
        f"&state={state}"
        f"&response_type=code"
    )
    return url


async def exchange_code_for_short_lived_token(code: str, redirect_uri: str) -> dict:
    logger.info("Exchanging code for short-lived token")
    async with httpx.AsyncClient() as client:
        response = await client.post(
            META_TOKEN_EXCHANGE_URL,
            data={
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "redirect_uri": redirect_uri,
                "code": code,
            },
        )
    try:
        data = response.json()
    except Exception:
        raise MetaAPIError("Invalid JSON response from Meta", status_code=response.status_code)
    if response.status_code >= 400 or "error" in data:
        error = data.get("error", {})
        if isinstance(error, dict):
            msg = error.get("message", data.get("error_description", "Meta OAuth error"))
        else:
            msg = data.get("error_description", str(error))
        raise MetaAPIError(msg, status_code=response.status_code, response_body=data)
    if "access_token" not in data:
        raise MetaAPIError("No access_token in Meta response", status_code=response.status_code, response_body=data)
    return data


async def exchange_for_long_lived_token(short_lived_token: str) -> dict:
    logger.info("Exchanging short-lived token for long-lived token")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            META_TOKEN_EXCHANGE_URL,
            params={
                "grant_type": "fb_exchange_token",
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "fb_exchange_token": short_lived_token,
            },
        )
    try:
        data = response.json()
    except Exception:
        raise MetaAPIError("Invalid JSON response from Meta", status_code=response.status_code)
    if response.status_code >= 400 or "error" in data:
        error = data.get("error", {})
        if isinstance(error, dict):
            msg = error.get("message", data.get("error_description", "Meta OAuth error"))
        else:
            msg = data.get("error_description", str(error))
        raise MetaAPIError(msg, status_code=response.status_code, response_body=data)
    if "access_token" not in data:
        raise MetaAPIError("No access_token in Meta long-lived token response", status_code=response.status_code, response_body=data)
    return data