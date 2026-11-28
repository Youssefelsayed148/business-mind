"""Read the Many side for one organization (Phase 5A). Staff only; read calls only.

Which Many channels belong to the organization:
- WhatsApp and Facebook: Many's workspace-scoped account lists for the mapped workspace.
- Instagram: Many's account list is global and does not name a workspace, so ownership comes from
  the organization's own channel connections plus explicit staff claims (``many_channel_claims``).
Leads come from Many's global staff list, which names channels but no workspace; the rules in
``service`` keep only leads on channels the organization owns.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import ChannelConnection, ManyChannelClaim, Tenant, User
from app.identity import many_proxy
from app.linking.service import PLATFORM_OF_CHANNEL, LeadRow, Snapshot

_ACCEPT = {"accept": "application/json"}
_LEAD_ID_FIELD = {
    "instagram": "instagram_account_id",
    "whatsapp": "whatsapp_account_id",
    "facebook": "facebook_page_id",
}


def _get(
    db: Session,
    settings: Settings,
    user: User,
    *,
    org_id: UUID | None,
    workspace_id: UUID | None,
    path: str,
) -> Any:
    token = many_proxy.many_token(
        db,
        settings,
        user,
        org_id=org_id,
        staff=True,
        fingerprint="staff",
        session_token_hash=None,
    )
    response = many_proxy.forward(
        settings,
        token=token,
        workspace_id=workspace_id,
        method="GET",
        path=path,
        query="",
        request_headers=_ACCEPT,
        body=None,
    )
    if response.status != 200:
        raise many_proxy.ManyUnavailable(f"{path} answered {response.status}")
    try:
        return json.loads(response.body)
    except ValueError as exc:
        raise many_proxy.ManyUnavailable(f"{path} answer unusable") from exc


def _ids(rows: Any) -> set[str]:
    if not isinstance(rows, list):
        raise many_proxy.ManyUnavailable("account list unusable")
    return {str(row["id"]) for row in rows if isinstance(row, dict) and row.get("id")}


def _leads(rows: Any) -> list[LeadRow]:
    if not isinstance(rows, list):
        raise many_proxy.ManyUnavailable("lead list unusable")
    out: list[LeadRow] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        platform = row.get("platform")
        external_id = row.get("ig_user_id")
        channel_id = row.get(_LEAD_ID_FIELD.get(str(platform), ""))
        if platform in _LEAD_ID_FIELD and external_id and channel_id and row.get("id"):
            out.append(LeadRow(str(row["id"]), platform, str(channel_id), str(external_id)))
    return out


def owned_channels(db: Session, tenant: Tenant) -> dict[str, set[str]]:
    """Channels the organization owns on the SaaS side: its connections and staff claims."""
    owned: dict[str, set[str]] = {"instagram": set(), "facebook": set(), "whatsapp": set()}
    connections = db.scalars(
        select(ChannelConnection).where(
            ChannelConnection.tenant_id == tenant.id,
            ChannelConnection.many_channel_ref.is_not(None),
        )
    )
    for connection in connections:
        platform = PLATFORM_OF_CHANNEL.get(connection.channel)
        if platform and connection.many_channel_ref:
            owned[platform].add(connection.many_channel_ref)
    for claim in db.scalars(
        select(ManyChannelClaim).where(ManyChannelClaim.tenant_id == tenant.id)
    ):
        owned[claim.platform].add(claim.many_channel_id)
    return owned


def fetch_snapshot(db: Session, settings: Settings, user: User, tenant: Tenant) -> Snapshot:
    """Raises ``many_proxy.ManyUnavailable`` when Many does not answer usefully."""
    owned = owned_channels(db, tenant)
    workspace = tenant.many_workspace_id
    if workspace is not None:
        owned["whatsapp"] |= _ids(
            _get(
                db,
                settings,
                user,
                org_id=tenant.id,
                workspace_id=workspace,
                path="whatsapp/accounts",
            )
        )
        owned["facebook"] |= _ids(
            _get(
                db,
                settings,
                user,
                org_id=tenant.id,
                workspace_id=workspace,
                path="facebook/accounts",
            )
        )
    leads = _leads(_get(db, settings, user, org_id=None, workspace_id=None, path="leads"))
    return Snapshot(leads=leads, owned=owned)
