"""Assigning location scope (design 4.2, Phase 3 PR D): invitations, role changes, agency grants.

Synthetic data only.
"""

import secrets
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.models import (
    AgencyGrantLocation,
    AuditEvent,
    Bot,
    Invitation,
    InvitationLocation,
    Location,
    Membership,
    MembershipLocation,
    User,
)
from app.identity import agency as svc
from app.identity.team import _guard_last_privileged
from tests.helpers import csrf_headers
from tests.identity_helpers import join, make_person, make_tenant
from tests.test_agency_grants import Scenario, _setup
from tests.test_location_filters import (
    World,
    _connection,
    _conversation,
    build_world,
    ids_in,
)
from tests.test_team_management import accept_new, token_of


def invite(w: World, who: Any, **body: Any) -> Any:
    payload = {"email": f"inv-{uuid4().hex[:8]}@example.com", "role": "agent", **body}
    return who.client.post(
        w.url("/team/invitations"), json=payload, headers=csrf_headers(who.client)
    )


def members_locations(db: Session, w: World, user_id: UUID) -> set[UUID]:
    return set(
        db.scalars(
            select(MembershipLocation.location_id).where(
                MembershipLocation.tenant_id == w.tenant_id, MembershipLocation.user_id == user_id
            )
        )
    )


def test_a_limited_invitation_carries_its_locations_into_the_new_account(
    v2_app: FastAPI, db: Session
) -> None:
    w = build_world(v2_app, db)
    address = f"north-{uuid4().hex[:8]}@example.com"
    response = invite(
        w, w.full_admin, email=address, location_scope="limited", location_ids=[str(w.north)]
    )
    assert response.status_code == 202, response.text
    invitation = db.scalar(select(Invitation).where(Invitation.email == address))
    assert invitation is not None and invitation.location_scope == "limited"
    assert set(
        db.scalars(
            select(InvitationLocation.location_id).where(
                InvitationLocation.invitation_id == invitation.id
            )
        )
    ) == {w.north}
    audit = db.scalar(select(AuditEvent).where(AuditEvent.action == "team.invited"))
    assert audit is not None
    anonymous = TestClient(v2_app, raise_server_exceptions=False)
    accepted = accept_new(anonymous, token_of(response.json()["link_path"]))
    assert accepted.status_code == 200, accepted.text
    user = db.scalar(select(User).where(User.email == address))
    assert user is not None
    membership = db.get(Membership, (w.tenant_id, user.id))
    assert membership is not None and membership.location_scope == "limited"
    assert members_locations(db, w, user.id) == {w.north}
    # The new person really is limited: only the northern conversation is visible.
    every = (w.conv_north, w.conv_south, w.conv_org, w.conv_web)
    assert ids_in(anonymous.get(w.url("/inbox")), *every) == {w.conv_north}


def test_an_existing_account_accepting_a_limited_invitation_becomes_limited(
    v2_app: FastAPI, db: Session
) -> None:
    w = build_world(v2_app, db)
    person = make_person(v2_app, "existing", db=db)
    link = invite(
        w,
        w.full_admin,
        email=person.email,
        location_scope="limited",
        location_ids=[str(w.south)],
    ).json()["link_path"]
    accepted = person.client.post(
        "/api/v1/invitations/accept",
        json={"token": token_of(link)},
        headers=csrf_headers(person.client),
    )
    assert accepted.status_code == 200, accepted.text
    membership = db.get(Membership, (w.tenant_id, person.user_id))
    assert membership is not None and membership.location_scope == "limited"
    assert members_locations(db, w, person.user_id) == {w.south}
    assert ids_in(person.client.get(w.url("/inbox")), w.conv_north, w.conv_south) == {w.conv_south}


def test_scope_requests_are_validated(v2_app: FastAPI, db: Session) -> None:
    w = build_world(v2_app, db)
    other = build_world(v2_app, db, "Elsewhere")
    owner = make_person(v2_app, "owner", db=db)
    join(db, w.tenant_id, owner.user_id, "owner")
    archived = Location(id=uuid4(), tenant_id=w.tenant_id, name="Old", status="archived")
    db.add(archived)
    db.commit()
    admin = w.full_admin
    assert invite(w, admin, location_scope="limited").status_code == 422  # no locations
    assert invite(w, admin, location_ids=[str(w.north)]).status_code == 422  # ids need limited
    assert (
        invite(w, admin, location_scope="limited", location_ids=[str(uuid4())]).status_code == 404
    )
    assert (
        invite(w, admin, location_scope="limited", location_ids=[str(other.north)]).status_code
        == 404
    )
    assert (
        invite(w, admin, location_scope="limited", location_ids=[str(archived.id)]).status_code
        == 404
    )
    assert invite(w, admin, location_scope="everything").status_code == 422
    # An Owner always sees every location.
    assert (
        invite(
            w, owner, role="owner", location_scope="limited", location_ids=[str(w.north)]
        ).status_code
        == 422
    )
    # Nothing was stored by the refused requests.
    assert db.scalar(select(InvitationLocation.invitation_id)) is None


def test_a_limited_person_cannot_change_the_team(v2_app: FastAPI, db: Session) -> None:
    w = build_world(v2_app, db)
    refused = invite(w, w.lim_admin, location_scope="limited", location_ids=[str(w.north)])
    assert refused.status_code == 403
    assert invite(w, w.lim_both).status_code == 403
    patch = w.lim_admin.client.patch(
        w.url(f"/team/members/{w.lim_agent.user_id}"),
        json={"role": "viewer"},
        headers=csrf_headers(w.lim_admin.client),
    )
    assert patch.status_code == 403
    gone = w.lim_admin.client.delete(
        w.url(f"/team/members/{w.lim_agent.user_id}"), headers=csrf_headers(w.lim_admin.client)
    )
    assert gone.status_code == 403
    # Reading the team list is still allowed and shows each member's locations.
    listing = w.lim_admin.client.get(w.url("/team/members"))
    assert listing.status_code == 200
    rows = {row["email"]: row for row in listing.json()}
    assert rows[w.lim_agent.email]["location_scope"] == "limited"
    assert rows[w.lim_agent.email]["location_ids"] == [str(w.north)]
    assert rows[w.lim_both.email]["location_ids"] == sorted([str(w.north), str(w.south)])
    assert rows[w.full_agent.email]["location_ids"] == []


def test_role_change_can_set_keep_and_clear_the_scope(v2_app: FastAPI, db: Session) -> None:
    w = build_world(v2_app, db)
    admin = w.full_admin
    target = w.lim_agent
    path = w.url(f"/team/members/{target.user_id}")
    headers = csrf_headers(admin.client)
    # Role only: a limited member stays limited, with the same locations.
    kept = admin.client.patch(path, json={"role": "manager"}, headers=headers)
    assert kept.status_code == 200, kept.text
    assert kept.json()["location_scope"] == "limited" and kept.json()["location_ids"] == [
        str(w.north)
    ]
    # A new set of locations replaces the old one and ends the person's sessions.
    moved = admin.client.patch(
        path,
        json={"role": "manager", "location_scope": "limited", "location_ids": [str(w.south)]},
        headers=headers,
    )
    assert moved.status_code == 200, moved.text
    assert members_locations(db, w, target.user_id) == {w.south}
    assert target.client.get(w.url("/inbox")).status_code == 401
    # Back to every location removes the list entirely.
    cleared = admin.client.patch(
        path, json={"role": "manager", "location_scope": "all"}, headers=headers
    )
    assert cleared.status_code == 200 and cleared.json()["location_ids"] == []
    assert members_locations(db, w, target.user_id) == set()
    membership = db.get(Membership, (w.tenant_id, target.user_id))
    assert membership is not None
    db.refresh(membership)
    assert membership.location_scope == "all"
    # Validation: ids with scope all, an empty limited scope, another organization's location.
    other = build_world(v2_app, db, "Elsewhere")
    for body, status in (
        ({"role": "manager", "location_scope": "all", "location_ids": [str(w.north)]}, 422),
        ({"role": "manager", "location_scope": "limited"}, 422),
        ({"role": "manager", "location_ids": [str(w.north)]}, 422),
        ({"role": "manager", "location_scope": "limited", "location_ids": [str(other.north)]}, 404),
    ):
        assert admin.client.patch(path, json=body, headers=headers).status_code == status, body
    audit = db.scalars(select(AuditEvent).where(AuditEvent.action == "team.role_changed")).all()
    assert audit and all("location_scope" in event.metadata_json for event in audit)


def test_a_limited_admin_does_not_count_as_the_last_admin(v2_app: FastAPI, db: Session) -> None:
    tenant_id = make_tenant(db, "Guard")
    sole = make_person(v2_app, "sole", db=db)
    limited = make_person(v2_app, "lim", db=db)
    join(db, tenant_id, sole.user_id, "admin")
    join(db, tenant_id, limited.user_id, "admin", location_scope="limited")
    target = db.get(Membership, (tenant_id, sole.user_id))
    assert target is not None
    # The only unrestricted admin cannot be removed or demoted: the other admin is limited.
    for new_role in (None, "agent", "limited"):
        with pytest.raises(ApiError) as error:
            _guard_last_privileged(db, tenant_id, target, new_role)
        assert error.value.status_code == 403
    second = make_person(v2_app, "second", db=db)
    join(db, tenant_id, second.user_id, "admin")
    _guard_last_privileged(db, tenant_id, target, "agent")  # a second unrestricted admin exists


def test_grants_can_be_limited_to_locations_and_the_assignee_sees_only_those(
    v2_app: FastAPI, db: Session
) -> None:
    s: Scenario = _setup(v2_app, db)
    bot = Bot(
        id=uuid4(),
        tenant_id=s.tenant_id,
        name="Bot",
        status="draft",
        config={},
        widget_locator="w" + secrets.token_hex(16),
    )
    north = Location(id=uuid4(), tenant_id=s.tenant_id, name="North")
    south = Location(id=uuid4(), tenant_id=s.tenant_id, name="South")
    db.add_all([bot, north, south])
    db.flush()
    conn_n = _connection(db, s.tenant_id, bot.id, "N", north.id, "n")
    conn_s = _connection(db, s.tenant_id, bot.id, "S", south.id, "s")
    conv_n = _conversation(db, s.tenant_id, bot.id, conn_n)
    conv_s = _conversation(db, s.tenant_id, bot.id, conn_s)
    conv_w = _conversation(db, s.tenant_id, bot.id, None)
    db.commit()
    # The Owner grants through the API with a location list.
    created = s.owner.client.post(
        s.url("/agency/grants"),
        json={
            "agency_id": str(s.agency.id),
            "role_cap": "manager",
            "location_ids": [str(north.id)],
        },
        headers=csrf_headers(s.owner.client),
    )
    assert created.status_code == 201, created.text
    grant = created.json()
    assert grant["location_ids"] == [str(north.id)]
    assert set(db.scalars(select(AgencyGrantLocation.location_id))) >= {north.id}
    svc.assign_grantee(
        db,
        actor=db.get(User, s.agency_admin.user_id),  # type: ignore[arg-type]
        grant_id=UUID(grant["id"]),
        user_id=s.agent.user_id,
    )
    db.commit()
    every = (conv_n, conv_s, conv_w)
    seen = ids_in(s.agent.client.get(s.url("/inbox")), *every)
    assert seen == {conv_n}  # the located grant hides the other location and org-wide rows
    assert s.agent.client.get(s.url(f"/conversations/{conv_s}")).status_code == 404
    assert s.agent.client.get(s.url(f"/conversations/{conv_n}")).status_code == 200
