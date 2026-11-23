import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.comment import Comment
from app.utils.normalization import normalize_comment

logger = logging.getLogger(__name__)


def upsert_comment(
    db: Session,
    instagram_account_id: uuid.UUID,
    comment_id: str,
    ig_user_id: str | None,
    username: str | None,
    comment_text: str,
) -> tuple[Comment, bool]:
    """Upsert a comment row.

    Returns (comment, is_duplicate).
    """
    existing = db.query(Comment).filter(Comment.comment_id == comment_id).first()
    if existing:
        logger.info("Duplicate comment ignored", extra={"comment_id": comment_id})
        return existing, True

    comment = Comment(
        id=uuid.uuid4(),
        instagram_account_id=instagram_account_id,
        comment_id=comment_id,
        ig_user_id=ig_user_id,
        ig_username=username,
        message=comment_text,
        normalized_text=normalize_comment(comment_text),
        received_at=datetime.now(timezone.utc),
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    logger.info("Comment stored", extra={"comment_id": comment_id})
    return comment, False
