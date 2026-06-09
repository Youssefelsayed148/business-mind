import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.meta_token import MetaToken
from app.utils.crypto import decrypt_text, encrypt_text

logger = logging.getLogger(__name__)


def store_encrypted_token(
    db: Session,
    workspace_id,
    instagram_account_id,
    access_token: str,
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
) -> MetaToken:
    encrypted = encrypt_text(access_token)
    token = MetaToken(
        instagram_account_id=instagram_account_id,
        access_token=encrypted,
        token_type="long_lived",
        status="active",
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    if expires_at is not None and hasattr(token, "expires_at"):
        token.expires_at = expires_at
        db.commit()
    logger.info("Stored encrypted token", extra={"token_id": str(token.id)})
    return token


def get_decrypted_token(db: Session, instagram_account_id) -> str | None:
    token = (
        db.query(MetaToken)
        .filter(
            MetaToken.instagram_account_id == instagram_account_id,
            MetaToken.status == "active",
        )
        .order_by(MetaToken.created_at.desc())
        .first()
    )
    if not token:
        return None
    return decrypt_text(token.access_token)


def mark_token_expiring_soon(db: Session, token_id) -> None:
    token = db.query(MetaToken).filter(MetaToken.id == token_id).first()
    if token:
        token.status = "expiring_soon"
        db.commit()
        logger.info("Marked token expiring soon", extra={"token_id": str(token_id)})


def mark_token_expired(db: Session, token_id) -> None:
    token = db.query(MetaToken).filter(MetaToken.id == token_id).first()
    if token:
        token.status = "expired"
        db.commit()
        logger.info("Marked token expired", extra={"token_id": str(token_id)})


def get_tokens_expiring_within(db: Session, days: int) -> list[MetaToken]:
    # TODO: Implement once expires_at field is tracked on MetaToken
    logger.info("Fetching tokens expiring within days", extra={"days": days})
    return []


def refresh_token_placeholder(db: Session, token_id) -> None:
    logger.info("Refresh token placeholder called", extra={"token_id": str(token_id)})
    # TODO: Implement real refresh once Meta endpoint is confirmed.
