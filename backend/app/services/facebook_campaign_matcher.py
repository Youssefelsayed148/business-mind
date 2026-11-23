import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.facebook_campaign import FacebookCampaign
from app.services.campaign_matcher import find_matching_keyword

logger = logging.getLogger(__name__)


@dataclass
class FacebookMatchResult:
    campaign_id: UUID
    matched_keyword: str


def find_matching_facebook_campaigns(
    db: Session,
    facebook_page_id: UUID,
    post_id: str | None,
    comment_text: str,
) -> list[FacebookMatchResult]:
    """Facebook equivalent of campaign_matcher.find_matching_campaigns.

    A new function rather than an extension of the Instagram one:
    Campaign.instagram_account_id is NOT NULL and find_matching_campaigns()
    is hard-typed to it — there's no generic seam to extend, only a pattern
    to mirror. Reuses find_matching_keyword() directly (pure text-matching,
    no Instagram-specific behavior) rather than reimplementing it.
    """
    query = db.query(FacebookCampaign).filter(
        FacebookCampaign.facebook_page_id == facebook_page_id,
        FacebookCampaign.status == "active",
    )

    campaigns = query.all()
    results: list[FacebookMatchResult] = []

    for campaign in campaigns:
        if campaign.target_scope == "specific_post":
            if not campaign.target_post_id:
                logger.warning(
                    "Active specific_post Facebook campaign has no target_post_id and can "
                    "never match; re-select its post",
                    extra={"campaign_id": str(campaign.id), "post_id": post_id},
                )
                continue
            if not post_id or campaign.target_post_id != post_id:
                continue
        keywords = [ck.normalized_keyword for ck in campaign.keywords]
        matched = find_matching_keyword(comment_text, keywords, campaign.match_type)
        if matched:
            results.append(
                FacebookMatchResult(
                    campaign_id=campaign.id,
                    matched_keyword=matched,
                )
            )

    return results
