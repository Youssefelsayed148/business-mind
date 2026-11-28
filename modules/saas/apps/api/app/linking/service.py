"""Link Many leads to SaaS contacts by channel identity (Phase 5A, docs/DATA-UNIFICATION.md 4).

Pure rules plus one database writer. No network here: ``fetch.py`` builds the snapshot.

Rules: one row per (tenant, platform, Many channel, external id digest). A person seen on both
sides is ``linked``; only in Many is ``many_only``; only in the SaaS is ``saas_only``; an identity
that resolves to two SaaS contacts is a ``conflict`` and is never resolved here. There is no
matching by phone, name or email, and none across channels or tenants. Leads on channels the
organization does not own are ignored.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import ChannelConnection, ContactIdentity, CustomerLink

# SaaS channel name for each Many platform.
SAAS_CHANNEL = {"instagram": "instagram", "facebook": "messenger", "whatsapp": "whatsapp"}
PLATFORM_OF_CHANNEL = {channel: platform for platform, channel in SAAS_CHANNEL.items()}


def link_digest(tenant_id: UUID, platform: str, many_channel_id: str, external_id: str) -> str:
    """Pseudonymous, tenant- and channel-scoped digest; the raw id is never stored here.

    Same family as the erasure fence (``channels.erasure.identity_digest``). It is not anonymous:
    a low-entropy id (a phone number) could be guessed against it, so the table is tenant data and
    goes away with the tenant. A keyed digest is a possible later hardening.
    """
    data = json.dumps(
        ["customer-link-v1", str(tenant_id), platform, many_channel_id, external_id],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LeadRow:
    many_lead_id: str
    platform: str
    many_channel_id: str
    external_id: str


@dataclass
class Snapshot:
    """What Many said, already reduced to what the rules need."""

    leads: list[LeadRow]
    # Many channel ids the organization owns, per platform.
    owned: dict[str, set[str]] = field(default_factory=dict)


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    skipped_erased: int = 0
    ignored_leads: int = 0
    by_state: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "skipped_erased": self.skipped_erased,
            "ignored_leads": self.ignored_leads,
            "by_state": dict(sorted(self.by_state.items())),
        }


@dataclass
class _Derived:
    contact_ids: set[UUID] = field(default_factory=set)
    many_lead_id: str | None = None


Key = tuple[str, str, str]  # platform, many channel id, digest


def derive(db: Session, tenant_id: UUID, snapshot: Snapshot) -> tuple[dict[Key, _Derived], int]:
    """The wanted state for every identity, and how many leads were ignored."""
    derived: dict[Key, _Derived] = defaultdict(_Derived)

    rows = db.execute(
        select(ContactIdentity, ChannelConnection.many_channel_ref)
        .join(ChannelConnection, ChannelConnection.id == ContactIdentity.connection_id)
        .where(
            ContactIdentity.tenant_id == tenant_id,
            ChannelConnection.tenant_id == tenant_id,
            ChannelConnection.many_channel_ref.is_not(None),
        )
    ).all()
    for identity, channel_ref in rows:
        platform = PLATFORM_OF_CHANNEL.get(identity.channel)
        if platform is None or channel_ref is None:
            continue
        key = (
            platform,
            channel_ref,
            link_digest(tenant_id, platform, channel_ref, identity.external_id),
        )
        derived[key].contact_ids.add(identity.contact_id)

    ignored = 0
    for lead in snapshot.leads:
        if lead.many_channel_id not in snapshot.owned.get(lead.platform, set()):
            ignored += 1
            continue
        key = (
            lead.platform,
            lead.many_channel_id,
            link_digest(tenant_id, lead.platform, lead.many_channel_id, lead.external_id),
        )
        derived[key].many_lead_id = lead.many_lead_id
    return dict(derived), ignored


def _state(item: _Derived) -> tuple[str, UUID | None]:
    if len(item.contact_ids) > 1:
        return "conflict", None
    contact_id = next(iter(item.contact_ids), None)
    if contact_id is not None and item.many_lead_id is not None:
        return "linked", contact_id
    if contact_id is not None:
        return "saas_only", contact_id
    return "many_only", None


def sync(db: Session, tenant_id: UUID, snapshot: Snapshot, *, dry_run: bool = False) -> SyncResult:
    """Make ``customer_links`` match the snapshot for one organization. Idempotent."""
    result = SyncResult()
    wanted, result.ignored_leads = derive(db, tenant_id, snapshot)
    existing = {
        (row.platform, row.many_channel_id, row.external_id_digest): row
        for row in db.scalars(select(CustomerLink).where(CustomerLink.tenant_id == tenant_id))
    }
    now = utcnow()
    for key, item in wanted.items():
        state, contact_id = _state(item)
        source = "many_lead" if item.many_lead_id is not None else "delegated_event"
        row = existing.get(key)
        if row is None:
            result.created += 1
            result.by_state[state] = result.by_state.get(state, 0) + 1
            if not dry_run:
                db.add(
                    CustomerLink(
                        tenant_id=tenant_id,
                        contact_id=contact_id,
                        platform=key[0],
                        many_channel_id=key[1],
                        external_id_digest=key[2],
                        many_lead_id=item.many_lead_id,
                        source=source,
                        state=state,
                    )
                )
            continue
        if row.state == "erased":
            result.skipped_erased += 1  # an erased person is never linked again
            continue
        result.by_state[state] = result.by_state.get(state, 0) + 1
        if (row.state, row.contact_id, row.many_lead_id) == (state, contact_id, item.many_lead_id):
            result.unchanged += 1
            continue
        result.updated += 1
        if not dry_run:
            row.state = state
            row.contact_id = contact_id
            row.many_lead_id = item.many_lead_id
            row.source = source
            row.updated_at = now
    if not dry_run:
        db.flush()
    return result
