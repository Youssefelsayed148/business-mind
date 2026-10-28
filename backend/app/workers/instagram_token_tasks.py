import logging

from app.db.session import SessionLocal
from app.services.log_service import log_action
from app.services.token_service import get_tokens_expiring_within, refresh_token
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Instagram long-lived tokens last 60 days; refresh once they are within this
# window so a few failed daily runs still leave time to react.
REFRESH_WINDOW_DAYS = 10

_ACTIONS = {
    "refreshed": "token_refreshed",
    "failed": "token_refresh_failed",
    "expired": "token_expired",
}


@celery_app.task(name="app.workers.instagram_token_tasks.refresh_expiring_instagram_tokens")
def refresh_expiring_instagram_tokens() -> dict:
    db = SessionLocal()
    counts = {"refreshed": 0, "too_young": 0, "expired": 0, "failed": 0}
    try:
        tokens = get_tokens_expiring_within(db, REFRESH_WINDOW_DAYS)
        for token in tokens:
            token_id = token.id
            account_id = token.instagram_account_id
            try:
                outcome = refresh_token(db, token)
            except Exception:
                db.rollback()
                logger.exception(
                    "Unexpected error refreshing Instagram token",
                    extra={"token_id": str(token_id)},
                )
                outcome = "failed"
            counts[outcome] += 1
            action = _ACTIONS.get(outcome)
            if action:
                db.refresh(token)
                log_action(
                    db,
                    action,
                    instagram_account_id=account_id,
                    details={
                        "token_id": str(token_id),
                        "expires_at": token.expires_at.isoformat() if token.expires_at else None,
                    },
                )
    finally:
        db.close()
    logger.info("Instagram token refresh run finished", extra=counts)
    return counts
