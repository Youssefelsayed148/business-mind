import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.facebook_token import FacebookToken
from app.utils.crypto import decrypt_text, encrypt_text

logger = logging.getLogger(__name__)


def store_encrypted_token(
    db: Session,
    facebook_page_id,
    access_token: str,
    expires_at: datetime | None = None,
    *, commit: bool = True,
) -> FacebookToken:
    encrypted = encrypt_text(access_token)
    token = FacebookToken(
        facebook_page_id=facebook_page_id,
        access_token=encrypted,
        token_type="page",
        status="active",
        expires_at=expires_at,
    )
    db.query(FacebookToken).filter(FacebookToken.facebook_page_id == facebook_page_id).delete(synchronize_session=False)
    db.add(token)
    db.flush()
    if commit:
        db.commit()
        db.refresh(token)
    logger.info("Stored encrypted Facebook Page token", extra={"token_id": str(token.id)})
    return token


def get_decrypted_token(db: Session, facebook_page_id) -> str | None:
    token = (
        db.query(FacebookToken)
        .filter(
            FacebookToken.facebook_page_id == facebook_page_id,
            FacebookToken.status == "active",
        )
        .order_by(FacebookToken.created_at.desc())
        .first()
    )
    if not token:
        return None
    return decrypt_text(token.access_token)


def mark_token_expiring_soon(db: Session, token_id) -> None:
    token = db.query(FacebookToken).filter(FacebookToken.id == token_id).first()
    if token:
        token.status = "expiring_soon"
        db.commit()
        logger.info("Marked Facebook token expiring soon", extra={"token_id": str(token_id)})


def mark_token_expired(db: Session, token_id) -> None:
    token = db.query(FacebookToken).filter(FacebookToken.id == token_id).first()
    if token:
        token.status = "expired"
        db.commit()
        logger.info("Marked Facebook token expired", extra={"token_id": str(token_id)})
