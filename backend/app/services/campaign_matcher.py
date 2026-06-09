import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.campaign import Campaign
from app.models.campaign_keyword import CampaignKeyword
from app.utils.normalization import normalize_comment

logger = logging.getLogger(__name__)


@dataclass
class MatchResult:
    campaign_id: UUID
    matched_keyword: str
    rendered_message_preview: str | None = None


def keyword_matches(comment_text: str, keyword: str, match_type: str) -> bool:
    normalized_comment = normalize_comment(comment_text)
    normalized_keyword = normalize_comment(keyword)

    if not normalized_comment or not normalized_keyword:
        return False

    if match_type == "exact":
        return normalized_comment == normalized_keyword
    elif match_type == "starts_with":
        return normalized_comment.startswith(normalized_keyword)
    else:  # contains
        return normalized_keyword in normalized_comment


def find_matching_keyword(
    comment_text: str, normalized_keywords: list[str], match_type: str
) -> str | None:
    for kw in normalized_keywords:
        if keyword_matches(comment_text, kw, match_type):
            return kw
    return None


def find_matching_campaigns(
    db: Session,
    instagram_account_id: UUID,
    media_id: str | None,
    comment_text: str,
) -> list[MatchResult]:
    query = db.query(Campaign).filter(
        Campaign.instagram_account_id == instagram_account_id,
        Campaign.status == "active",
    )

    campaigns = query.all()
    results: list[MatchResult] = []

    for campaign in campaigns:
        if campaign.target_scope == "specific_media":
            if not campaign.target_media_id:
                logger.debug(
                    "Specific media campaign waiting for media_id mapping",
                    extra={"campaign_id": str(campaign.id), "media_id": media_id},
                )
                continue
            if not media_id or campaign.target_media_id != media_id:
                continue
        keywords = [ck.normalized_keyword for ck in campaign.keywords]
        matched = find_matching_keyword(comment_text, keywords, campaign.match_type)
        if matched:
            results.append(
                MatchResult(
                    campaign_id=campaign.id,
                    matched_keyword=matched,
                )
            )

    return results
