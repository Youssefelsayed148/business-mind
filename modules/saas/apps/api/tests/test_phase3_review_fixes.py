"""Regression tests for the Phase 3 review findings (docs/PHASE-3-REVIEW.md).

Synthetic data only (example.com addresses, throwaway database).
"""

import csv
import io
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import (
    Bot,
    ContactIdentity,
    Invitation,
    Location,
    Membership,
    MembershipLocation,
    User,
)
from app.identity import agency as agency_service
from app.identity.roles import org_role_of
from app.inbox import listing
from tests.conftest import build_test_settings
from tests.helpers import csrf_headers
from tests.identity_helpers import Org, Person, join, make_person, make_tenant
from tests.knowledge_helpers import upload_settings
from tests.test_agency_grants import Scenario, _ctx, _setup
from tests.test_team_management import team_org, url


def _send(person: Person, method: str, target: str, body: Any = None) -> Any:
    headers = csrf_headers(person.client) if method != "GET" else {}
    return person.client.request(method, target, json=body, headers=headers)


def _code(response: Any) -> str:
    return str(response.json()["error"]["code"])


def _membership(db: Session, tenant_id: UUID, user_id: UUID) -> Membership:
    db.expire_all()
    row = db.get(Membership, (tenant_id, user_id))
    assert row is not None
    return row


def _effective(db: Session, tenant_id: UUID, user_id: UUID) -> str:
    row = _membership(db, tenant_id, user_id)
    return org_role_of(row.role, row.org_role)


def _limit_to_a_new_location(db: Session, tenant_id: UUID, user_id: UUID) -> UUID:
    place = Location(id=uuid4(), tenant_id=tenant_id, name=f"Here {uuid4().hex[:6]}")
    db.add(place)
    db.execute(
        update(Membership)
        .where(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
        .values(location_scope="limited")
    )
    db.flush()
    db.add(MembershipLocation(tenant_id=tenant_id, user_id=user_id, location_id=place.id))
    db.commit()
    return place.id


# --- 1. legacy team routes obey the identity-v2 team rules --------------------------------


def _legacy_invite(person: Person, org: Org, email: str, role: str) -> Any:
    return _send(person, "POST", url(org, "/invitations"), {"email": email, "role": role})


def _owner_invitation(db: Session, org: Org, app: FastAPI) -> tuple[UUID, str]:
    """An Owner invites a second Owner through the v2 team route."""
    invitee = make_person(app, "next-owner", db=db)
    owner = org.people["owner"]
    response = _send(
        owner, "POST", url(org, "/team/invitations"), {"email": invitee.email, "role": "owner"}
    )
    assert response.status_code == 202, response.text
    row = db.scalar(select(Invitation).where(Invitation.email == invitee.email))
    assert row is not None
    return row.id, invitee.email


def test_legacy_routes_do_not_let_an_admin_remove_or_demote_the_owner(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    admin, owner = org.people["admin"], org.people["owner"]
    removed = _send(admin, "DELETE", url(org, f"/members/{owner.user_id}"))
    assert removed.status_code == 403 and _code(removed) == "OWNER_REQUIRED", removed.text
    demoted = _send(admin, "PATCH", url(org, f"/members/{owner.user_id}"), {"role": "viewer"})
    assert demoted.status_code == 403 and _code(demoted) == "OWNER_REQUIRED", demoted.text
    assert _effective(db, org.tenant_id, owner.user_id) == "owner"
    assert _membership(db, org.tenant_id, owner.user_id).status == "active"


def test_legacy_routes_forbid_self_edit_and_an_admin_assigning_admin(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    admin, viewer = org.people["admin"], org.people["viewer"]
    own = _send(admin, "DELETE", url(org, f"/members/{admin.user_id}"))
    assert own.status_code == 403 and _code(own) == "SELF_EDIT", own.text
    promoted = _send(admin, "PATCH", url(org, f"/members/{viewer.user_id}"), {"role": "admin"})
    assert promoted.status_code == 403 and _code(promoted) == "OWNER_REQUIRED", promoted.text
    assert _effective(db, org.tenant_id, viewer.user_id) == "viewer"


def test_legacy_role_change_writes_both_role_columns(v2_app: FastAPI, db: Session) -> None:
    org = team_org(v2_app, db)
    admin, manager = org.people["admin"], org.people["manager"]
    # "editor" is what a Manager already is in the legacy vocabulary: nothing changes.
    same = _send(admin, "PATCH", url(org, f"/members/{manager.user_id}"), {"role": "editor"})
    assert same.status_code == 200, same.text
    assert _effective(db, org.tenant_id, manager.user_id) == "manager"
    down = _send(admin, "PATCH", url(org, f"/members/{manager.user_id}"), {"role": "viewer"})
    assert down.status_code == 200 and down.json()["role"] == "viewer", down.text
    row = _membership(db, org.tenant_id, manager.user_id)
    assert (row.role, row.org_role) == ("viewer", "viewer")


def test_legacy_removal_works_for_members_below_the_actor(v2_app: FastAPI, db: Session) -> None:
    org = team_org(v2_app, db)
    admin, agent = org.people["admin"], org.people["agent"]
    assert _send(admin, "DELETE", url(org, f"/members/{agent.user_id}")).status_code == 204
    assert _membership(db, org.tenant_id, agent.user_id).status == "revoked"


def test_legacy_invitations_need_an_owner_for_the_admin_role(v2_app: FastAPI, db: Session) -> None:
    org = team_org(v2_app, db)
    admin, owner = org.people["admin"], org.people["owner"]
    invitee = make_person(v2_app, "joiner", db=db)
    refused = _legacy_invite(admin, org, invitee.email, "admin")
    assert refused.status_code == 403 and _code(refused) == "OWNER_REQUIRED", refused.text
    allowed = _legacy_invite(owner, org, invitee.email, "admin")
    assert allowed.status_code == 201, allowed.text
    row = db.scalar(select(Invitation).where(Invitation.email == invitee.email))
    assert row is not None and (row.role, row.org_role) == ("admin", "admin")
    below = make_person(v2_app, "helper", db=db)
    created = _legacy_invite(admin, org, below.email, "editor")
    assert created.status_code == 201, created.text
    lower = db.scalar(select(Invitation).where(Invitation.email == below.email))
    assert lower is not None and (lower.role, lower.org_role) == ("editor", "agent")


def test_an_admin_cannot_resend_or_revoke_a_privileged_invitation(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    admin, owner = org.people["admin"], org.people["owner"]
    invitation_id, _ = _owner_invitation(db, org, v2_app)
    resent = _send(admin, "POST", url(org, f"/invitations/{invitation_id}/resend"))
    assert resent.status_code == 403 and _code(resent) == "OWNER_REQUIRED", resent.text
    assert "token=" not in resent.text
    revoked = _send(admin, "DELETE", url(org, f"/invitations/{invitation_id}"))
    assert revoked.status_code == 403 and _code(revoked) == "OWNER_REQUIRED", revoked.text
    assert _send(owner, "POST", url(org, f"/invitations/{invitation_id}/resend")).status_code == 200
    assert _send(owner, "DELETE", url(org, f"/invitations/{invitation_id}")).status_code == 204


def test_a_location_limited_admin_cannot_use_legacy_team_writes(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    admin, viewer = org.people["admin"], org.people["viewer"]
    invitation_id, _ = _owner_invitation(db, org, v2_app)
    _limit_to_a_new_location(db, org.tenant_id, admin.user_id)
    invitee = make_person(v2_app, "wide", db=db)
    attempts = (
        _legacy_invite(admin, org, invitee.email, "viewer"),
        _send(admin, "PATCH", url(org, f"/members/{viewer.user_id}"), {"role": "editor"}),
        _send(admin, "DELETE", url(org, f"/members/{viewer.user_id}")),
        _send(admin, "POST", url(org, f"/invitations/{invitation_id}/resend")),
        _send(admin, "DELETE", url(org, f"/invitations/{invitation_id}")),
    )
    for response in attempts:
        assert response.status_code == 403, response.text
    assert _membership(db, org.tenant_id, viewer.user_id).status == "active"


# --- 2. older writers cannot leave a stale organization role behind -----------------------


def _platform(staff: Person, method: str, path: str, body: Any = None) -> Any:
    return _send(staff, method, f"/api/v1/platform/users{path}", body)


def test_a_demotion_made_with_the_flag_off_survives_turning_it_on(
    app: FastAPI, db: Session
) -> None:
    org = team_org(app, db)  # org_role filled, as migration 0034 leaves it
    admin, manager = org.people["admin"], org.people["manager"]
    response = _send(admin, "PATCH", url(org, f"/members/{manager.user_id}"), {"role": "viewer"})
    assert response.status_code == 200, response.text
    assert _effective(db, org.tenant_id, manager.user_id) == "viewer"


@pytest.mark.parametrize("flag", [False, True])
def test_a_staff_demotion_takes_effect(app: FastAPI, db: Session, flag: bool) -> None:
    app.dependency_overrides[get_settings] = lambda: build_test_settings(identity_v2_enabled=flag)
    org = team_org(app, db)
    staff = make_person(app, "staff", staff=True, db=db)
    target = org.people["admin"]
    response = _platform(
        staff,
        "PATCH",
        f"/{target.user_id}/memberships/{org.tenant_id}",
        {"role": "viewer"},
    )
    assert response.status_code == 200, response.text
    assert _effective(db, org.tenant_id, target.user_id) == "viewer"


def test_a_removed_owner_added_again_comes_back_with_the_new_role(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    staff = make_person(v2_app, "staff", staff=True, db=db)
    owner = org.people["owner"]
    second = make_person(v2_app, "second-owner", db=db)
    join(db, org.tenant_id, second.user_id, "owner")
    path = f"/{owner.user_id}/memberships/{org.tenant_id}"
    assert _platform(staff, "DELETE", path).status_code == 204
    again = _platform(
        staff,
        "POST",
        f"/{owner.user_id}/memberships",
        {"organization_id": str(org.tenant_id), "role": "viewer"},
    )
    assert again.status_code == 201, again.text
    assert _effective(db, org.tenant_id, owner.user_id) == "viewer"


def test_staff_cannot_remove_or_demote_the_only_owner(v2_app: FastAPI, db: Session) -> None:
    org = team_org(v2_app, db)
    staff = make_person(v2_app, "staff", staff=True, db=db)
    owner = org.people["owner"]
    path = f"/{owner.user_id}/memberships/{org.tenant_id}"
    demoted = _platform(staff, "PATCH", path, {"role": "viewer"})
    assert demoted.status_code == 403 and _code(demoted) == "LAST_OWNER", demoted.text
    removed = _platform(staff, "DELETE", path)
    assert removed.status_code == 403 and _code(removed) == "LAST_OWNER", removed.text
    assert _effective(db, org.tenant_id, owner.user_id) == "owner"


# --- 3. organization-wide data needs unrestricted access ----------------------------------


@pytest.mark.parametrize("path", ["/data/export", "/data/audit"])
def test_a_location_limited_admin_cannot_read_organization_wide_data(
    v2_app: FastAPI, db: Session, path: str
) -> None:
    org = team_org(v2_app, db)
    admin = org.people["admin"]
    assert admin.client.get(url(org, path)).status_code == 200
    _limit_to_a_new_location(db, org.tenant_id, admin.user_id)
    refused = admin.client.get(url(org, path))
    assert refused.status_code == 403, refused.text
    assert org.people["owner"].client.get(url(org, path)).status_code == 200


# --- 4. agency access works within its cap ------------------------------------------------

AGENCY_READS = (
    "/contacts",
    "/contacts/stages",
    "/follow-ups",
    "/inbox",
    "/inbox/counts",
    "/analytics",
    "/analytics/timeseries",
    "/channels",
    "/quota",
    "/bots",
    "/contacts/export.csv",
    "/data/export",
    "/data/audit",
)


def test_agency_admin_cap_reads_without_server_errors(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    s.grant(cap="admin")
    failures = []
    for path in AGENCY_READS:
        response = s.agent.client.get(s.url(path))
        if response.status_code != 200:
            failures.append(f"{path}: {response.status_code} {response.text[:120]}")
    assert not failures, "\n".join(failures)


def test_agency_export_leaves_out_the_clients_team(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    s.grant(cap="admin")
    exported = s.agent.client.get(s.url("/data/export"))
    assert exported.status_code == 200, exported.text
    body = exported.json()
    assert "members" not in body and "invitations" not in body
    assert s.owner.email not in str(body["tenant"])
    own = s.owner.client.get(s.url("/data/export")).json()
    assert own["members"] and "invitations" in own


def test_a_location_limited_agency_grant_cannot_export_the_organization(
    v2_app: FastAPI, db: Session
) -> None:
    s = _setup(v2_app, db)
    place = Location(id=uuid4(), tenant_id=s.tenant_id, name="Only here")
    db.add(place)
    db.commit()
    s.grant(cap="admin", location_ids=[place.id])
    for path in ("/data/export", "/data/audit"):
        assert s.agent.client.get(s.url(path)).status_code == 403, path


def test_agency_caps_are_enforced_on_writes(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    s.grant(cap="agent")
    created = _send(
        s.agent, "POST", s.url("/contacts"), {"email": f"lead-{uuid4().hex[:8]}@example.com"}
    )
    assert created.status_code == 201, created.text
    assert s.agent.client.get(s.url("/contacts/export.csv")).status_code == 403
    cancelled = _send(s.agent, "DELETE", s.url(f"/follow-ups/{uuid4()}"))
    assert cancelled.status_code == 404, cancelled.text


def _agency_stream(s: Scenario) -> Any:
    return listing.event_stream(s.tenant_id, s.agent.user_id, None, None, via_agency=True)


def test_the_live_inbox_stays_open_for_agency_access_until_the_grant_ends(
    v2_app: FastAPI, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(listing, "INBOX_POLL_SECONDS", 0)
    s = _setup(v2_app, db)
    grant = s.grant(cap="viewer")
    stream = _agency_stream(s)
    try:
        assert "inbox.ready" in next(stream)
        assert next(stream) == ": keep-alive\n\n"
        agency_service.revoke_grant(_ctx(db, s.tenant_id, s.owner), grant_id=grant.id)
        db.commit()
        assert "inbox.access_revoked" in next(stream)
    finally:
        stream.close()


def test_the_events_route_tells_the_stream_about_agency_access(
    v2_app: FastAPI, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[dict[str, Any]] = []

    def fake_stream(*args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return iter([": done\n\n"])

    monkeypatch.setattr(listing, "event_stream", fake_stream)
    s = _setup(v2_app, db)
    s.grant(cap="viewer")
    assert s.agent.client.get(s.url("/inbox/events")).status_code == 200
    assert s.owner.client.get(s.url("/inbox/events")).status_code == 200
    assert seen == [{"via_agency": True}, {}]


# --- 5. clients edit knowledge (decision D5) ----------------------------------------------


def _knowledge_org(app: FastAPI, db: Session, tmp_path: Path, *, flag: bool) -> tuple[Org, str]:
    app.dependency_overrides[get_settings] = lambda: upload_settings(tmp_path).model_copy(
        update={"identity_v2_enabled": flag, "login_rate_limit_attempts": 1000}
    )
    org = team_org(app, db)
    bot = Bot(
        id=uuid4(),
        tenant_id=org.tenant_id,
        name="Bot",
        status="draft",
        config={},
        widget_locator="w" + uuid4().hex,
    )
    db.add(bot)
    db.commit()
    return org, url(org, f"/bots/{bot.id}")


def _upload(person: Person, base: str, body: bytes) -> Any:
    return person.client.post(
        f"{base}/sources/files",
        files=[("files", ("notes.txt", body, "text/plain"))],
        headers=csrf_headers(person.client),
    )


@pytest.mark.parametrize("role", ["owner", "admin", "manager"])
def test_clients_with_knowledge_write_can_manage_sources(
    app: FastAPI, db: Session, tmp_path: Path, role: str
) -> None:
    org, base = _knowledge_org(app, db, tmp_path, flag=True)
    person = org.people[role]
    uploaded = _upload(person, base, f"Opening hours for {role}: nine to five.".encode())
    assert uploaded.status_code == 201, uploaded.text
    source_id = uploaded.json()[0]["id"]
    started = _send(person, "POST", f"{base}/ingestion", {"source_ids": [source_id]})
    assert started.status_code == 202, started.text
    assert person.client.get(f"{base}/sources/qa-template").status_code == 200


def test_knowledge_writes_stay_closed_below_manager_and_for_limited_access(
    app: FastAPI, db: Session, tmp_path: Path
) -> None:
    org, base = _knowledge_org(app, db, tmp_path, flag=True)
    for role in ("agent", "viewer"):
        assert _upload(org.people[role], base, b"no").status_code == 403, role
    manager = org.people["manager"]
    _limit_to_a_new_location(db, org.tenant_id, manager.user_id)
    refused = _upload(manager, base, b"Only one location should not edit everything.")
    assert refused.status_code == 403, refused.text
    # Bot configuration and retrieval settings stay staff-only.
    assert org.people["owner"].client.get(f"{base}/rag").status_code == 403


def test_knowledge_stays_staff_only_with_the_flag_off(
    app: FastAPI, db: Session, tmp_path: Path
) -> None:
    org, base = _knowledge_org(app, db, tmp_path, flag=False)
    refused = _upload(org.people["admin"], base, b"not for clients yet")
    assert refused.status_code == 403
    assert "Only platform staff" in refused.text
    assert org.people["admin"].client.get(f"{base}/sources/qa-template").status_code == 403


# --- 8. large contact exports -------------------------------------------------------------


def test_contact_export_works_beyond_the_bind_parameter_limit(app: FastAPI, db: Session) -> None:
    total = 66_000  # PostgreSQL allows 65,535 bind parameters in one statement
    tenant_id = make_tenant(db, "Big")
    admin = make_person(app, "big-admin", db=db)
    join(db, tenant_id, admin.user_id, "admin")
    db.execute(
        text(
            """
            INSERT INTO contacts (id, tenant_id, display_name, source_channel, stage,
                                  tags, custom_fields, consent, created_at, updated_at)
            SELECT gen_random_uuid(), :tenant, 'c' || g, 'whatsapp', 'new',
                   '[]'::jsonb, '{}'::jsonb, '{}'::jsonb, now(), now()
            FROM generate_series(1, :total) AS g
            """
        ),
        {"tenant": tenant_id, "total": total},
    )
    first = db.execute(
        text("SELECT id FROM contacts WHERE tenant_id = :t AND display_name = 'c1'"),
        {"t": tenant_id},
    ).scalar_one()
    db.add(
        ContactIdentity(
            tenant_id=tenant_id, contact_id=first, channel="whatsapp", external_id="synthetic-1"
        )
    )
    db.commit()
    response = TestClient(app, raise_server_exceptions=False, cookies=admin.client.cookies).get(
        f"/api/v1/tenants/{tenant_id}/contacts/export.csv"
    )
    assert response.status_code == 200, response.text[:200]
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == total
    assert {row["channels"] for row in rows if row["display_name"] == "c1"} == {"whatsapp"}


# --- 9. who may reset another person's MFA ------------------------------------------------


def _enrolled(db: Session, user_id: UUID) -> None:
    db.execute(text("UPDATE users SET mfa_enrolled_at = now() WHERE id = :u"), {"u": user_id})
    db.commit()


def _reset(actor: Person, org: Org, target: UUID) -> Any:
    return _send(actor, "POST", url(org, f"/team/members/{target}/mfa-reset"))


def _still_enrolled(db: Session, user_id: UUID) -> bool:
    db.expire_all()
    user = db.get(User, user_id)
    assert user is not None
    return user.mfa_enrolled_at is not None


@pytest.mark.parametrize("kind", ["platform_staff", "other_organization", "agency_person"])
def test_only_staff_reset_mfa_for_people_who_reach_beyond_the_organization(
    v2_app: FastAPI, db: Session, kind: str
) -> None:
    org = team_org(v2_app, db)
    staff = make_person(v2_app, "staff", staff=True, db=db)
    target = make_person(v2_app, "shared", staff=kind == "platform_staff", db=db)
    join(db, org.tenant_id, target.user_id, "agent")
    if kind == "other_organization":
        join(db, make_tenant(db, "Elsewhere"), target.user_id, "viewer")
    if kind == "agency_person":
        creator = db.get(User, staff.user_id)
        assert creator is not None
        studio = agency_service.create_agency(db, actor=creator, name="Studio")
        agency_service.add_agency_member(
            db, actor=creator, agency_id=studio.id, user_id=target.user_id
        )
        db.commit()
    _enrolled(db, target.user_id)
    refused = _reset(org.people["owner"], org, target.user_id)
    assert refused.status_code == 403 and _code(refused) == "STAFF_REQUIRED", refused.text
    assert _still_enrolled(db, target.user_id)
    assert _reset(staff, org, target.user_id).status_code == 204
    assert not _still_enrolled(db, target.user_id)


def test_a_revoked_membership_elsewhere_does_not_block_an_owner_reset(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    target = org.people["agent"]
    old = make_tenant(db, "Former")
    join(db, old, target.user_id, "viewer")
    db.execute(
        update(Membership)
        .where(Membership.tenant_id == old, Membership.user_id == target.user_id)
        .values(status="revoked")
    )
    db.commit()
    _enrolled(db, target.user_id)
    assert _reset(org.people["owner"], org, target.user_id).status_code == 204
