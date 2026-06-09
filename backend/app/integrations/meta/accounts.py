import logging

import httpx

from app.core.config import settings
from app.integrations.meta.client import MetaGraphClient
from app.integrations.meta.errors import MetaAPIError

logger = logging.getLogger(__name__)


async def fetch_instagram_account_metadata(long_lived_token: str) -> dict:
    logger.info("Fetching Instagram account metadata")
    api_base = f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}"

    # Step A: fetch the Facebook Pages this user manages (each carries its own page token)
    async with httpx.AsyncClient() as http:
        response = await http.get(
            f"{api_base}/me/accounts",
            params={"access_token": long_lived_token, "fields": "id,name,access_token"},
        )
    try:
        pages_data = response.json()
    except Exception:
        raise MetaAPIError("Invalid JSON response from Meta /me/accounts", status_code=response.status_code)
    if response.status_code >= 400 or "error" in pages_data:
        error = pages_data.get("error", {})
        msg = error.get("message", "Failed to fetch Facebook Pages") if isinstance(error, dict) else str(error)
        raise MetaAPIError(msg, status_code=response.status_code, response_body=pages_data)

    pages = pages_data.get("data", [])

    # Steps B & C: find the first Page that has a linked Instagram Business Account, then fetch its details
    ig_account_id = None
    client = MetaGraphClient()
    try:
        for page in pages:
            page_id = page.get("id")
            page_token = page.get("access_token")
            if not page_id or not page_token:
                continue
            try:
                page_result = await client.get(
                    f"/{page_id}",
                    access_token=page_token,
                    params={"fields": "instagram_business_account"},
                )
            except MetaAPIError:
                continue
            iba = page_result.get("instagram_business_account")
            if iba:
                ig_account_id = iba.get("id")
                break

        if not ig_account_id:
            raise MetaAPIError("No Instagram Business Account found linked to this Facebook account")

        ig_data = await client.get(
            f"/{ig_account_id}",
            access_token=long_lived_token,
            params={"fields": "id,username,profile_picture_url,followers_count,name"},
        )
    finally:
        await client.close()

    return {
        "ig_user_id": ig_data.get("id", ""),
        "username": ig_data.get("username", ""),
        "profile_picture_url": ig_data.get("profile_picture_url") or None,
        "followers_count": int(ig_data.get("followers_count", 0)),
        "name": ig_data.get("name") or ig_data.get("username", ""),
    }
