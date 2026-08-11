import logging

from app.core.config import settings
from app.integrations.meta.client import MetaGraphClient

logger = logging.getLogger(__name__)


async def fetch_instagram_account_metadata(access_token: str) -> dict:
    """Fetch the app user's Instagram professional account profile.

    Instagram Login tokens are scoped directly to the app user's IG business
    account, so a single GET to graph.instagram.com/{version}/me suffices — no
    Facebook Page lookup is involved. Verified against
    https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started
    (fields: id, user_id, username, name, account_type, profile_picture_url,
    followers_count, follows_count, media_count).
    """
    logger.info("Fetching Instagram account metadata")
    client = MetaGraphClient(base_url=f"https://graph.instagram.com/{settings.META_GRAPH_API_VERSION}")
    try:
        result = await client.get(
            "/me",
            access_token=access_token,
            params={"fields": "id,user_id,username,name,account_type,profile_picture_url,followers_count"},
        )
    finally:
        await client.close()

    # Docs show /me returning {"data": [...]}; some responses are flat. Normalize.
    wrapped = result.get("data")
    data = wrapped[0] if isinstance(wrapped, list) and wrapped else result

    ig_user_id = data.get("user_id") or data.get("id") or ""
    return {
        "ig_user_id": str(ig_user_id),
        "username": data.get("username") or "",
        "profile_picture_url": data.get("profile_picture_url") or None,
        "followers_count": int(data.get("followers_count") or 0),
        "name": data.get("name") or data.get("username") or "",
    }
