"""Durable account erasure. Callers own the transaction; no network or sends."""
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.account_erasure_job import AccountErasureJob
from app.models.audit_log import AuditLog
from app.models.lead import Lead
from app.models.meta_authorization import MetaAuthorization
from app.models.saas_forward_event import SaasForwardEvent
from app.models.whatsapp_campaign import WhatsappCampaign
from app.models.whatsapp_contact import WhatsappContact
from app.services.contact_erasure import ACCOUNT_FK, erasure_event_id
from app.services.meta_compliance import CHANNELS
from app.services.saas_forwarder import enqueue_event
from app.services.scoped_account_deletion import erase_owned_rows


def _scope_lock(db: Session, platform: str, channel_id: UUID) -> None:
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
               {"key": f"account-erasure:{platform}:{channel_id}"})


def _lock_forwards(db: Session, platform: str, channel_id: UUID) -> None:
    # Same ordering locks as the HTTP forwarder, before channel row locks.
    keys = db.query(SaasForwardEvent.ordering_key).filter(
        SaasForwardEvent.platform == platform, SaasForwardEvent.channel_id == channel_id).distinct().all()
    for (key,) in sorted(keys):
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": key})


def begin_erasure(db: Session, *, workspace_id: UUID, platform: str, channel_id: UUID) -> AccountErasureJob | None:
    if platform not in CHANNELS:
        raise ValueError("unsupported platform")
    _scope_lock(db, platform, channel_id)
    existing = db.query(AccountErasureJob).filter_by(workspace_id=workspace_id, platform=platform, channel_id=channel_id).first()
    if existing:
        return existing
    _lock_forwards(db, platform, channel_id)
    model, token, fk = CHANNELS[platform]
    channel = db.query(model).filter(model.id == channel_id, model.workspace_id == workspace_id).with_for_update().one_or_none()
    if channel is None:
        return None
    now = datetime.now(timezone.utc)
    job = AccountErasureJob(id=uuid4(), request_id=uuid4(), workspace_id=workspace_id, platform=platform,
                            channel_id=channel_id, state="pending", event_ids=[], identity_count=0, accepted_count=0)
    db.add(job)
    channel.status = "erasure_pending"
    channel.ai_enabled = False
    channel.saas_delegation_enabled = False
    if hasattr(channel, "ai_cold_dm_enabled"):
        channel.ai_cold_dm_enabled = False
    db.query(token).filter(getattr(token, fk) == channel_id).delete(synchronize_session=False)
    if platform == "whatsapp":
        channel.outreach_paused = True
        channel.outreach_paused_reason = "account_erasure_pending"
        channel.outreach_paused_at = now
        db.query(WhatsappCampaign).filter(WhatsappCampaign.whatsapp_account_id == channel_id).update(
            {"status": "cancelled"}, synchronize_session=False)

    identities = set()
    for lead in db.query(Lead).filter(getattr(Lead, ACCOUNT_FK[platform]) == channel_id, Lead.workspace_id == workspace_id).all():
        identity = lead.facebook_psid if platform == "facebook" else lead.ig_user_id
        if identity:
            identities.add(identity)
    if platform == "whatsapp":
        identities.update(value for (value,) in db.query(WhatsappContact.wa_id).filter(
            WhatsappContact.whatsapp_account_id == channel_id, WhatsappContact.workspace_id == workspace_id).all() if value)
    rows = db.query(SaasForwardEvent).filter(SaasForwardEvent.platform == platform, SaasForwardEvent.channel_id == channel_id).all()
    existing_erasures = [row for row in rows if row.event_type == "contact.erasure"]
    unknown_scope = False
    for event in rows:
        if event.event_type == "contact.erasure" and event.status == "sent":
            # Older senders accepted any 2xx; those rows lack durable proof of
            # the contract's exact 202 and need independent operator evidence.
            unknown_scope = True
        if event.event_type in ("message.received", "contact.erasure"):
            identity = (event.payload or {}).get("external_contact_id")
            if isinstance(identity, str) and identity.strip():
                identities.add(identity)
            elif event.event_type == "message.received":
                # Already-cleared history cannot prove the remote identity set.
                unknown_scope = True
    configured = bool(channel.saas_connection_id and channel.saas_base_url and channel.saas_secret_encrypted)
    if not identities:
        # No durable history proof is available, even if delegation is off now.
        unknown_scope = True
    reused = {row.payload.get("external_contact_id") for row in existing_erasures if row.payload}
    for identity in sorted(identities - reused):
        event_id = erasure_event_id(platform, channel_id, identity, job.request_id)
        enqueue_event(db, platform=platform, channel=channel, ordering_key="erasure:" + event_id,
            event_id=event_id, event_type="contact.erasure", now=now,
            payload={"version": 1, "event_id": event_id, "event_type": "contact.erasure",
                     "connection_id": channel.saas_connection_id, "external_contact_id": identity,
                     "occurred_at": now.isoformat().replace("+00:00", "Z")})
    db.flush()
    erasures = db.query(SaasForwardEvent).filter(SaasForwardEvent.platform == platform,
        SaasForwardEvent.channel_id == channel_id, SaasForwardEvent.event_type == "contact.erasure").all()
    job.event_ids = [row.id for row in erasures]
    job.identity_count = len(erasures)
    if not configured:
        job.state, job.error_code = "operator_action", "missing_signing_configuration"
    elif unknown_scope:
        job.state, job.error_code = "operator_action", "unknown_remote_scope"
    else:
        job.state = "waiting_remote_acceptance"
    if db.query(AuditLog.id).filter(AuditLog.entity_id.is_(None)).first():
        # Historical text without an entity boundary cannot be attributed by
        # email/name. Retain it for explicit local operator review.
        job.state, job.error_code = "operator_action", "audit_scope_unproven"
    # Outbox creation and customer deletion share the caller's transaction.
    erase_owned_rows(db, platform=platform, channel=channel)
    db.flush()
    return job


def advance_erasure(db: Session, job_id: UUID, *, remote_cleanup_verified: bool = False,
                    local_scope_verified: bool = False) -> AccountErasureJob:
    initial = db.get(AccountErasureJob, job_id)
    if initial is None:
        raise ValueError("erasure job not found")
    _scope_lock(db, initial.platform, initial.channel_id)
    _lock_forwards(db, initial.platform, initial.channel_id)
    job = db.query(AccountErasureJob).filter_by(id=job_id).populate_existing().with_for_update().one()
    now = datetime.now(timezone.utc)
    if job.error_code == "audit_scope_unproven" and not local_scope_verified:
        return job
    if remote_cleanup_verified:
        # Only the explicit local operator workflow may supply this assertion.
        job.remote_verified_at = now
    if job.state == "local_erased":
        return job
    events = db.query(SaasForwardEvent).filter(SaasForwardEvent.id.in_(job.event_ids)).all()
    job.accepted_count = sum(event.status == "sent" for event in events)
    if not job.remote_verified_at:
        if job.error_code in ("missing_signing_configuration", "unknown_remote_scope", "audit_scope_unproven"):
            return job
        if len(events) != job.identity_count or any(event.status in ("failed", "dropped") for event in events):
            job.state, job.error_code = "operator_action", "remote_not_accepted"
            return job
        if job.accepted_count != job.identity_count:
            job.state = "waiting_remote_acceptance"
            return job
    model, token, fk = CHANNELS[job.platform]
    channel = db.query(model).filter(model.id == job.channel_id, model.workspace_id == job.workspace_id).with_for_update().one_or_none()
    if channel is None:
        job.state, job.error_code = "operator_action", "channel_missing"
        return job
    if channel.status != "erasure_pending":
        # Stale jobs cannot remove a reconnected/new grant.
        job.state, job.error_code = "operator_action", "unknown_remote_scope"
        return job
    erase_owned_rows(db, platform=job.platform, channel=channel)
    db.query(token).filter(getattr(token, fk) == channel.id).delete(synchronize_session=False)
    for event in events:
        event.payload = {}
    db.flush()
    db.query(SaasForwardEvent).filter(SaasForwardEvent.id.in_(job.event_ids)).delete(synchronize_session=False)
    # Authorization is the last child removed, in the account transaction.
    db.query(MetaAuthorization).filter(MetaAuthorization.workspace_id == job.workspace_id,
        MetaAuthorization.platform == job.platform, MetaAuthorization.channel_id == job.channel_id).delete(synchronize_session=False)
    db.delete(channel)
    job.state, job.error_code, job.local_erased_at = "local_erased", None, now
    db.flush()
    return job


def sweep_erasure_jobs(db: Session) -> None:
    ids = [row[0] for row in db.query(AccountErasureJob.id).filter(AccountErasureJob.state != "local_erased").all()]
    for job_id in ids:
        advance_erasure(db, job_id)
        db.commit()
    # Acceptance alone does not start the 30-day ledger retention period.
    db.query(AccountErasureJob).filter(AccountErasureJob.state == "local_erased",
        AccountErasureJob.remote_verified_at < datetime.now(timezone.utc) - timedelta(days=30)).delete(synchronize_session=False)
    db.commit()
