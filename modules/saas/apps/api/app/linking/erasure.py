"""One erasure request for one person on one channel, in the SaaS and in Many (Phase 5C).

Order (docs/DATA-UNIFICATION.md section 6): record the case, erase the SaaS side with the existing
audited routine (``channels.erasure.erase_channel_contact``), then ask Many to erase with the same
request id through Many's existing ``/privacy/contact-erasure`` route. A failure on the Many side
never undoes the SaaS erase: the case keeps a reason and can be retried, and a repeat with the same
request id is safe on both sides.

The raw external id stays on the link row only until the case completes (Many has to be told whom to
erase). The case holds no identifier, name or message.

Erasing one channel identity deletes the SaaS contact (the existing routine does that); the same
person's links on other channels stay until each is erased too.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.channels.erasure import erase_channel_contact
from app.core.audit import record_audit
from app.core.config import Settings
from app.core.errors import ApiError
from app.db.models import ChannelConnection, ChannelEvent, CustomerLink, ErasureCase, Tenant, User
from app.identity import many_proxy
from app.linking.service import SAAS_CHANNEL

_SAFE_SEGMENT = re.compile(r"[A-Za-z0-9_.-]{1,128}")
_JSON = {"content-type": "application/json", "accept": "application/json"}


def _now() -> datetime:
    return datetime.now(UTC)


def _case_for(db: Session, tenant_id: UUID, request_id: UUID) -> ErasureCase | None:
    return db.scalar(
        select(ErasureCase).where(
            ErasureCase.tenant_id == tenant_id, ErasureCase.request_id == request_id
        )
    )


def _set(case: ErasureCase, state: str, reason: str | None = None) -> None:
    case.state = state
    case.reason = reason
    case.updated_at = _now()
    if state == "complete":
        case.completed_at = _now()


def start(
    db: Session,
    settings: Settings,
    user: User,
    tenant: Tenant,
    link: CustomerLink,
    request_id: UUID,
    session_hash: str | None,
) -> ErasureCase:
    """Begin (or repeat) one erasure. Idempotent by ``request_id``."""
    existing = _case_for(db, tenant.id, request_id)
    if existing is not None:
        if existing.link_id != link.id:
            raise ApiError(409, "REQUEST_ID_REUSED", "This request id belongs to another request.")
        return existing
    if link.state == "erased":
        raise ApiError(409, "ALREADY_ERASED", "This person is already erased.")
    if not link.external_id:
        raise ApiError(
            409,
            "IDENTITY_UNAVAILABLE",
            "The identity is not known here yet. Ask staff to run the sync, then try again.",
        )
    case = ErasureCase(
        tenant_id=tenant.id,
        request_id=request_id,
        link_id=link.id,
        platform=link.platform,
        many_channel_id=link.many_channel_id,
        state="requested",
        requested_by=user.id,
    )
    db.add(case)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()  # a simultaneous request with the same id won the race
        raced = _case_for(db, tenant.id, request_id)
        if raced is None:
            raise
        return raced
    record_audit(
        db,
        action="customer_erasure.requested",
        tenant_id=tenant.id,
        actor_user_id=user.id,
        target_type="erasure_case",
        target_id=str(case.id),
        metadata={"platform": link.platform},
    )
    db.commit()  # durable before any side effect
    return resume(db, settings, user, tenant, case, session_hash)


def resume(
    db: Session,
    settings: Settings,
    user: User,
    tenant: Tenant,
    case: ErasureCase,
    session_hash: str | None,
) -> ErasureCase:
    """Continue a case from where it stopped. Safe to call again."""
    if case.state == "complete":
        return case
    # Two retries at once must not both run: lock the case row until this call commits (G-01).
    db.execute(select(ErasureCase.id).where(ErasureCase.id == case.id).with_for_update())
    db.refresh(case)
    if case.state == "complete":
        return case
    link = db.get(CustomerLink, case.link_id) if case.link_id else None
    if link is None or link.tenant_id != tenant.id:
        _set(case, "needs_action", "link_missing")
        db.commit()
        return case
    if case.state in ("requested", "needs_action") and link.state != "erased":
        if not _erase_saas(db, tenant, case, link):
            return case  # nothing was erased in the SaaS: do not ask Many either
    _ask_many(db, settings, user, tenant, case, link, session_hash)
    return case


def _erase_saas(db: Session, tenant: Tenant, case: ErasureCase, link: CustomerLink) -> bool:
    connection = db.scalar(
        select(ChannelConnection).where(
            ChannelConnection.tenant_id == tenant.id,
            ChannelConnection.many_channel_ref == link.many_channel_id,
            ChannelConnection.channel == SAAS_CHANNEL[link.platform],
        )
    )
    if connection is None and link.contact_id is not None:
        # A contact is still attached but its channel connection cannot be found: nothing was
        # erased, so the link must not be marked erased (security review G-02).
        _set(case, "needs_action", "connection_missing")
        db.commit()
        return False
    if connection is not None and link.external_id:
        event_id = f"customer-erasure-{case.id}"
        # A retry after a crash between the erase commit and the case update finds the event
        # that already ran; it must not insert it again (security review G-01).
        already = db.scalar(
            select(ChannelEvent.id).where(
                ChannelEvent.connection_id == connection.id,
                ChannelEvent.event_id == event_id,
            )
        )
        if already is None:
            event = ChannelEvent(
                tenant_id=tenant.id,
                connection_id=connection.id,
                event_id=event_id,
                event_type="contact.erasure",
                payload={"external_contact_id": link.external_id},
                status="received",
            )
            db.add(event)
            db.flush()
            erase_channel_contact(db, event, uuid4())  # commits
            db.refresh(case)
            db.refresh(link)
    link.state = "erased"
    link.display_name = None
    link.many_lead_id = None
    link.contact_id = None
    link.updated_at = _now()
    _set(case, "saas_erased")
    record_audit(
        db,
        action="customer_erasure.saas_erased",
        tenant_id=tenant.id,
        actor_user_id=case.requested_by,
        target_type="erasure_case",
        target_id=str(case.id),
        metadata={"platform": case.platform},
    )
    db.commit()
    return True


def _ask_many(
    db: Session,
    settings: Settings,
    user: User,
    tenant: Tenant,
    case: ErasureCase,
    link: CustomerLink,
    session_hash: str | None,
) -> None:
    if tenant.many_workspace_id is None or not link.external_id:
        _set(
            case,
            "needs_action",
            "workspace_not_mapped" if not tenant.many_workspace_id else "identity_unavailable",
        )
        db.commit()
        return
    if not _SAFE_SEGMENT.fullmatch(case.many_channel_id) or case.many_channel_id in (".", ".."):
        # The channel reference is staff-set text: never let it change the Many path (G-04).
        _set(case, "needs_action", "channel_ref_invalid")
        db.commit()
        return
    path = f"privacy/contact-erasure/{case.platform}/{case.many_channel_id}"
    body = json.dumps(
        {"request_id": str(case.request_id), "external_contact_id": link.external_id}
    ).encode("utf-8")
    try:
        token = many_proxy.many_token(
            db,
            settings,
            user,
            org_id=tenant.id,
            staff=user.is_platform_staff,
            fingerprint="staff" if user.is_platform_staff else "customer-erasure",
            session_token_hash=session_hash,
        )
        response = many_proxy.forward(
            settings,
            token=token,
            workspace_id=tenant.many_workspace_id,
            method="POST",
            path=path,
            query="",
            request_headers=_JSON,
            body=body,
        )
    except (many_proxy.ManyUnavailable, ApiError):
        _set(case, "needs_action", "many_unavailable")
        db.commit()
        return
    if response.status in (200, 202):
        try:
            answer = json.loads(response.body)
        except ValueError:
            answer = {}
        if isinstance(answer, dict) and answer.get("local_status") == "erased":
            case.many_event_id = str(answer.get("event_id") or "")[:100] or None
            case.many_remote_status = str(answer.get("remote_status") or "")[:50] or None
            link.external_id = None  # no longer needed: nothing left to ask
            link.updated_at = _now()
            _set(case, "complete")
            record_audit(
                db,
                action="customer_erasure.complete",
                tenant_id=tenant.id,
                actor_user_id=case.requested_by,
                target_type="erasure_case",
                target_id=str(case.id),
                metadata={"platform": case.platform},
            )
            db.commit()
            return
        _set(case, "needs_action", "many_answer_unusable")
    elif response.status == 404:
        _set(case, "needs_action", "many_channel_not_found")
    elif response.status in (401, 403):
        _set(case, "needs_action", "many_forbidden")
    elif response.status == 429:
        _set(case, "needs_action", "many_rate_limited")
    else:
        _set(case, "needs_action", "many_unavailable")
    db.commit()


REASON_TEXT = {
    "many_unavailable": "The outreach service did not answer. Try again in a moment.",
    "many_rate_limited": "The outreach service is busy. Try again in a minute.",
    "many_forbidden": "The outreach service refused the request. Ask staff to check your access.",
    "many_channel_not_found": (
        "The outreach service does not know this channel. Ask staff to check the mapping."
    ),
    "many_answer_unusable": "The outreach service gave an unexpected answer. Ask staff to check.",
    "workspace_not_mapped": (
        "This organization is not connected to the outreach service. Ask staff."
    ),
    "identity_unavailable": "The identity is no longer stored here. Ask staff.",
    "link_missing": "The person's record is gone. Ask staff.",
    "connection_missing": (
        "The channel connection for this person cannot be found, so nothing was erased. Ask staff."
    ),
    "channel_ref_invalid": "The channel reference is not valid. Ask staff to check the mapping.",
}
