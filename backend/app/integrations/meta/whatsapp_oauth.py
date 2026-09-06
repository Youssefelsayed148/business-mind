import logging

import httpx

from app.core.config import settings
from app.integrations.meta.errors import MetaAPIError

logger = logging.getLogger(__name__)

# WhatsApp Cloud API / Embedded Signup lives entirely on graph.facebook.com —
# unlike Instagram Login (graph.instagram.com / api.instagram.com), there is
# no separate Instagram-style OAuth authorize/redirect page: the frontend
# uses the Facebook JS SDK's FB.login() with a config_id (Embedded Signup),
# which returns an authorization `code` client-side (plus phone_number_id /
# waba_id via a postMessage "WA_EMBEDDED_SIGNUP" event, not through this
# module). This module only does the server-side code -> token exchange and
# the two Graph API calls needed to finish onboarding a number.
GRAPH_BASE = "https://graph.facebook.com"


def _raise_meta_error(response: httpx.Response, data: dict, fallback: str) -> None:
    error = data.get("error")
    if isinstance(error, dict):
        msg = error.get("message") or fallback
    else:
        msg = fallback
    raise MetaAPIError(msg, status_code=response.status_code, response_body=data)


async def exchange_code_for_token(code: str) -> dict:
    """Exchange the Embedded Signup authorization code for a short-lived,
    customer-scoped access token.

    Endpoint: GET /{version}/oauth/access_token — no redirect_uri, since
    Embedded Signup is a client-side FB.login() popup flow, not a
    server-redirect OAuth flow like Instagram Login's.
    """
    logger.info("Exchanging WhatsApp Embedded Signup code for access token")
    url = f"{GRAPH_BASE}/{settings.META_GRAPH_API_VERSION}/oauth/access_token"
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            params={
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "code": code,
            },
        )
    try:
        data = response.json()
    except Exception:
        raise MetaAPIError("Invalid JSON response from Meta", status_code=response.status_code)
    if response.status_code >= 400 or "error" in data:
        _raise_meta_error(response, data, "WhatsApp OAuth code exchange failed")
    if "access_token" not in data:
        raise MetaAPIError(
            "No access_token in WhatsApp token response",
            status_code=response.status_code,
            response_body=data,
        )
    return data


async def exchange_for_long_lived_token(short_lived_token: str) -> dict:
    """Exchange a short-lived user token for a long-lived one (~60 days)."""
    logger.info("Exchanging WhatsApp short-lived token for long-lived token")
    url = f"{GRAPH_BASE}/{settings.META_GRAPH_API_VERSION}/oauth/access_token"
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
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
        _raise_meta_error(response, data, "WhatsApp long-lived token exchange failed")
    if "access_token" not in data:
        raise MetaAPIError(
            "No access_token in WhatsApp long-lived token response",
            status_code=response.status_code,
            response_body=data,
        )
    return data


async def fetch_phone_number_metadata(access_token: str, phone_number_id: str) -> dict:
    """Fetch display name/number for a WhatsApp Cloud API phone number.

    Endpoint: GET /{phone_number_id}?fields=display_phone_number,verified_name
    """
    logger.info("Fetching WhatsApp phone number metadata")
    url = f"{GRAPH_BASE}/{settings.META_GRAPH_API_VERSION}/{phone_number_id}"
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            params={"fields": "display_phone_number,verified_name", "access_token": access_token},
        )
    try:
        data = response.json()
    except Exception:
        raise MetaAPIError("Invalid JSON response from Meta", status_code=response.status_code)
    if response.status_code >= 400 or "error" in data:
        _raise_meta_error(response, data, "Failed to fetch WhatsApp phone number metadata")
    return data


async def subscribe_app_to_waba(access_token: str, waba_id: str) -> None:
    """Subscribe this app to the customer's WhatsApp Business Account so its
    webhooks (inbound messages, status updates) are delivered to us.

    Endpoint: POST /{waba_id}/subscribed_apps — required once per WABA,
    otherwise no webhook events are ever sent for numbers under it.
    """
    logger.info("Subscribing app to WhatsApp Business Account", extra={"waba_id": waba_id})
    url = f"{GRAPH_BASE}/{settings.META_GRAPH_API_VERSION}/{waba_id}/subscribed_apps"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, params={"access_token": access_token})
    try:
        data = response.json()
    except Exception:
        raise MetaAPIError("Invalid JSON response from Meta", status_code=response.status_code)
    if response.status_code >= 400 or "error" in data:
        _raise_meta_error(response, data, "Failed to subscribe app to WhatsApp Business Account")
