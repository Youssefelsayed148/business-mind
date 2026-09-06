import logging
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.whatsapp_token import WhatsappToken
from app.utils.crypto import decrypt_text, encrypt_text

logger = logging.getLogger(__name__)


def store_encrypted_token(
    db: Session,
    whatsapp_account_id,
    access_token: str,
    expires_at: datetime | None = None,
) -> WhatsappToken:
    encrypted = encrypt_text(access_token)
    token = WhatsappToken(
        whatsapp_account_id=whatsapp_account_id,
        access_token=encrypted,
        token_type="long_lived",
        status="active",
        expires_at=expires_at,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    logger.info("Stored encrypted WhatsApp token", extra={"token_id": str(token.id)})
    return token


def get_decrypted_token(db: Session, whatsapp_account_id) -> str | None:
    token = (
        db.query(WhatsappToken)
        .filter(
            WhatsappToken.whatsapp_account_id == whatsapp_account_id,
            WhatsappToken.status == "active",
        )
        .order_by(WhatsappToken.created_at.desc())
        .first()
    )
    if not token:
        return None
    return decrypt_text(token.access_token)


def mark_token_expiring_soon(db: Session, token_id) -> None:
    token = db.query(WhatsappToken).filter(WhatsappToken.id == token_id).first()
    if token:
        token.status = "expiring_soon"
        db.commit()
        logger.info("Marked WhatsApp token expiring soon", extra={"token_id": str(token_id)})


def mark_token_expired(db: Session, token_id) -> None:
    token = db.query(WhatsappToken).filter(WhatsappToken.id == token_id).first()
    if token:
        token.status = "expired"
        db.commit()
        logger.info("Marked WhatsApp token expired", extra={"token_id": str(token_id)})
