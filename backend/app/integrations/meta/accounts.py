import logging

from app.core.config import settings
from app.integrations.meta.client import MetaGraphClient

logger = logging.getLogger(__name__)


async def fetch_instagram_media(
    access_token: str,
    limit: int = 25,
    after: str | None = None,
) -> dict:
    """Fetch the connected Instagram account's published media for the post picker.

    Returns Instagram's own numeric media ids, which are the same identifier
    space the comments webhook delivers — so a campaign built from this list
    can be matched directly against incoming events. Parsing a pasted
    permalink yields a shortcode instead, which is NOT comparable to the
    webhook media_id.

    Endpoint: GET /me/media (Instagram Login, instagram_business_basic scope).
    """
    logger.info("Fetching Instagram media list", extra={"limit": limit, "has_cursor": bool(after)})
    client = MetaGraphClient(base_url=f"https://graph.instagram.com/{settings.META_GRAPH_API_VERSION}")
    params = {
        "fields": "id,caption,media_type,media_url,permalink,thumbnail_url,timestamp",
        "limit": limit,
    }
    if after:
        params["after"] = after

    try:
        result = await client.get("/me/media", access_token=access_token, params=params)
    finally:
        await client.close()

    items = result.get("data") or []
    media = []
    for item in items:
        caption = item.get("caption") or ""
        media.append(
            {
                "media_id": str(item.get("id") or ""),
                "caption": caption,
                "label": (caption[:80].strip() or "Untitled post"),
                "media_type": (item.get("media_type") or "unknown"),
                "media_url": item.get("media_url"),
                "permalink": item.get("permalink"),
                # Videos/reels have no media_url usable as an <img> src; use thumbnail.
                "thumbnail_url": item.get("thumbnail_url") or item.get("media_url"),
                "timestamp": item.get("timestamp"),
            }
        )

    paging = result.get("paging") or {}
    cursors = paging.get("cursors") or {}
    return {
        "media": media,
        "next_cursor": cursors.get("after") if paging.get("next") else None,
    }


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
        "provider_user_id": data.get("user_id"),
        "provider_profile_id": data.get("id"),
        "username": data.get("username") or "",
        "profile_picture_url": data.get("profile_picture_url") or None,
        "followers_count": int(data.get("followers_count") or 0),
        "name": data.get("name") or data.get("username") or "",
    }
