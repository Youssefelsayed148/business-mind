import logging

import httpx

from app.core.config import settings
from app.integrations.meta.errors import MetaAPIError

logger = logging.getLogger(__name__)

# Facebook Page connection uses "Facebook Login for Business" — the same
# product family as WhatsApp's Embedded Signup (config_id + client-side
# FB.login() popup, no server redirect URL), per this phase's research
# spike. Verify this against current Meta docs before relying on it — if it
# turns out Facebook Pages actually use the classic redirect-based "Facebook
# Login" instead, mirror app/integrations/meta/oauth.py's shape (Instagram's)
# rather than this file's.
GRAPH_BASE = "https://graph.facebook.com"


def _raise_meta_error(response: httpx.Response, data: dict, fallback: str) -> None:
    error = data.get("error")
    if isinstance(error, dict):
        msg = error.get("message") or fallback
    else:
        msg = fallback
    raise MetaAPIError(msg, status_code=response.status_code, response_body=data)


async def exchange_code_for_token(code: str) -> dict:
    """Exchange the Facebook Login for Business authorization code for a
    short-lived user access token. No redirect_uri — same reasoning as
    WhatsApp's Embedded Signup code exchange (client-side popup flow).
    """
    logger.info("Exchanging Facebook Login code for access token")
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
        _raise_meta_error(response, data, "Facebook OAuth code exchange failed")
    if "access_token" not in data:
        raise MetaAPIError(
            "No access_token in Facebook token response",
            status_code=response.status_code,
            response_body=data,
        )
    return data


async def exchange_for_long_lived_token(short_lived_token: str) -> dict:
    """Exchange a short-lived user token for a long-lived one (~60 days)."""
    logger.info("Exchanging Facebook short-lived token for long-lived token")
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
        _raise_meta_error(response, data, "Facebook long-lived token exchange failed")
    if "access_token" not in data:
        raise MetaAPIError(
            "No access_token in Facebook long-lived token response",
            status_code=response.status_code,
            response_body=data,
        )
    return data


async def list_granted_pages(user_access_token: str) -> list[dict]:
    """List the Pages this user granted access to during Login for Business.

    Endpoint: GET /me/accounts — each entry carries its own Page Access
    Token directly (no per-Page exchange step needed, unlike WhatsApp's
    phone-number flow), plus `id`/`name`. The dashboard shows this list so
    the user can pick which Page(s) to connect — a step WhatsApp's
    single-number flow didn't need.
    """
    logger.info("Listing Facebook Pages granted during Login for Business")
    url = f"{GRAPH_BASE}/{settings.META_GRAPH_API_VERSION}/me/accounts"
    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            params={"access_token": user_access_token, "fields": "id,name,access_token"},
        )
    try:
        data = response.json()
    except Exception:
        raise MetaAPIError("Invalid JSON response from Meta", status_code=response.status_code)
    if response.status_code >= 400 or "error" in data:
        _raise_meta_error(response, data, "Failed to list Facebook Pages")
    return data.get("data", [])


async def subscribe_app_to_page(page_access_token: str, page_id: str) -> None:
    """Subscribe this app to the Page so its webhooks (comments, Messenger
    messages) are delivered to us.

    Endpoint: POST /{page_id}/subscribed_apps — required once per Page,
    otherwise no webhook events are ever sent for it. Mirrors
    whatsapp_oauth.subscribe_app_to_waba's role for WABAs.
    """
    logger.info("Subscribing app to Facebook Page", extra={"page_id": page_id})
    url = f"{GRAPH_BASE}/{settings.META_GRAPH_API_VERSION}/{page_id}/subscribed_apps"
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            params={
                "access_token": page_access_token,
                "subscribed_fields": "feed,messages,messaging_postbacks",
            },
        )
    try:
        data = response.json()
    except Exception:
        raise MetaAPIError("Invalid JSON response from Meta", status_code=response.status_code)
    if response.status_code >= 400 or "error" in data:
        _raise_meta_error(response, data, "Failed to subscribe app to Facebook Page")
