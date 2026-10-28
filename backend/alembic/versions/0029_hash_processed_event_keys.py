"""Hash historical webhook dedupe keys and remove diagnostic personal data.

Revision ID:0029_hash_processed_event_keys
Revises:0028_meta_compliance

Pause old API/worker writers before this migration and deploy the matching
shared helper before resuming. The data transformation is deliberately not
reversible: downgrade removes schema guards, never reconstructs personal data.
Rollback to code expecting raw keys requires keeping processing paused.
"""
import hashlib
import re

from alembic import op
import sqlalchemy as sa

revision = "0029_hash_processed_event_keys"
down_revision = "0028_meta_compliance"
branch_labels = None
depends_on = None

_HASHED = re.compile(r"sha256:v1:[0-9a-f]{64}\Z")
_SAFE_TYPES = (
    "ig_comment", "ig_message", "ig_postback", "facebook_comment", "facebook_message",
    "whatsapp_message", "whatsapp_message_status", "whatsapp_template_status", "whatsapp_phone_quality",
)
_GUARDS = {
    "ck_processed_event_key_hashed": "event_key ~ '^sha256:v1:[0-9a-f]{64}$'",
    "ck_processed_event_metadata_empty": "metadata IS NULL",
    "ck_processed_event_type_safe": "event_type IS NULL OR event_type IN (" + ",".join(repr(value) for value in _SAFE_TYPES) + ")",
}


def _storage_key(value: str) -> str:
    if _HASHED.fullmatch(value):
        return value
    return "sha256:v1:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()
    # Serialize the whole rewrite with any in-flight writer. New constraints
    # subsequently refuse old raw-key writers rather than exposing personal data.
    bind.execute(sa.text("LOCK TABLE processed_webhook_events IN ACCESS EXCLUSIVE MODE"))
    bind.execute(sa.text("UPDATE processed_webhook_events SET metadata = NULL"))
    statement = sa.text("UPDATE processed_webhook_events SET event_type = NULL WHERE event_type NOT IN :types")
    bind.execute(statement.bindparams(sa.bindparam("types", expanding=True)), {"types": _SAFE_TYPES})
    last_id = None
    while True:
        condition = "WHERE id > :last_id" if last_id is not None else ""
        rows = bind.execute(sa.text(
            "SELECT id,provider,event_key,received_at FROM processed_webhook_events "
            + condition + " ORDER BY id LIMIT 500"
        ), {"last_id": last_id} if last_id is not None else {}).fetchall()
        if not rows:
            break
        last_id = rows[-1].id
        for row in rows:
            canonical = _storage_key(row.event_key)
            if canonical == row.event_key:
                continue
            duplicate = bind.execute(sa.text(
                "SELECT id FROM processed_webhook_events WHERE provider = :provider AND event_key = :key"
            ), {"provider": row.provider, "key": canonical}).first()
            if duplicate is not None:
                bind.execute(sa.text(
                    "UPDATE processed_webhook_events SET received_at = LEAST(received_at,:received) WHERE id = :id"
                ), {"received": row.received_at, "id": duplicate.id})
                bind.execute(sa.text("DELETE FROM processed_webhook_events WHERE id = :id"), {"id": row.id})
            else:
                bind.execute(sa.text("UPDATE processed_webhook_events SET event_key = :key WHERE id = :id"),
                             {"key": canonical, "id": row.id})
    # Current-model0001 may already create these guards on an empty database.
    # Recreate them after the rewrite so an incompatible old guard is not trusted.
    for name, expression in _GUARDS.items():
        bind.execute(sa.text(f'ALTER TABLE processed_webhook_events DROP CONSTRAINT IF EXISTS "{name}"'))
        op.create_check_constraint(name, "processed_webhook_events", expression)


def downgrade() -> None:
    for name in reversed(_GUARDS):
        op.execute(sa.text(f'ALTER TABLE processed_webhook_events DROP CONSTRAINT IF EXISTS "{name}"'))
    # Keep opaque keys and erased metadata. Never restore identifiers/text.
