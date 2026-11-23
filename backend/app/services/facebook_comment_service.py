import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.facebook_comment import FacebookComment
from app.utils.normalization import normalize_comment

logger = logging.getLogger(__name__)


def upsert_facebook_comment(
    db: Session,
    facebook_page_id: uuid.UUID,
    comment_id: str,
    post_id: str | None,
    from_id: str | None,
    from_name: str | None,
    comment_text: str,
) -> tuple[FacebookComment, bool]:
    """Upsert a Facebook comment row. Returns (comment, is_duplicate).

    Mirrors comment_service.upsert_comment — a new function rather than an
    extension, since Comment.instagram_account_id is NOT NULL.
    """
    existing = db.query(FacebookComment).filter(FacebookComment.comment_id == comment_id).first()
    if existing:
        logger.info("Duplicate Facebook comment ignored", extra={"comment_id": comment_id})
        return existing, True

    comment = FacebookComment(
        id=uuid.uuid4(),
        facebook_page_id=facebook_page_id,
        comment_id=comment_id,
        post_id=post_id,
        from_id=from_id,
        from_name=from_name,
        message=comment_text,
        normalized_text=normalize_comment(comment_text),
        received_at=datetime.now(timezone.utc),
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    logger.info("Facebook comment stored", extra={"comment_id": comment_id})
    return comment, False
