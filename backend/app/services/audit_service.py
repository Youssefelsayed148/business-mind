import uuid

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog
from app.models.user import User


def actor_fields(actor: User | None) -> dict:
    return {
        "actor_user_id": actor.id if actor else None,
        "actor_email": actor.email if actor else None,
    }


def write_audit_log(
    db: Session,
    action: str,
    message: str,
    *,
    actor: User | None = None,
    actor_email: str | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    entity_name: str | None = None,
    severity: str = "info",
    metadata: dict | None = None,
    commit: bool = True,
) -> AuditLog:
    log = AuditLog(
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else actor_email,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_name=entity_name,
        severity=severity,
        message=message,
        metadata_=metadata or {},
    )
    db.add(log)
    if commit:
        db.commit()
        db.refresh(log)
    return log
