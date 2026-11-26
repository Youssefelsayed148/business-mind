"""Agency grants (design 4.3): structural isolation, caps, expiry, revocation, audit."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.tenancy import TenantContext
from app.db.base import utcnow
from app.db.models import (
    Agency,
    AgencyGrant,
    AgencyMembership,
    AuditEvent,
    Location,
    Membership,
    Tenant,
    User,
)
from app.identity import agency as svc
from app.identity.access import resolve_access
from app.identity.roles import agency_permissions
from tests.helpers import PASSWORD, csrf_headers
from tests.identity_helpers import Person, join, make_person, make_tenant

FORBIDDEN = "You do not have permission for this action."


def _user(db: Session, person: Person) -> User:
    user = db.get(User, person.user_id)
    assert user is not None
    return user


def _ctx(db: Session, tenant_id: UUID, person: Person) -> TenantContext:
    tenant = db.get(Tenant, tenant_id)
    assert tenant is not None
    return TenantContext(
        db=db,
        user=_user(db, person),
        tenant=tenant,
        membership=db.get(Membership, (tenant_id, person.user_id)),
    )


@dataclass
class Scenario:
    db: Session
    tenant_id: UUID
    owner: Person
    admin: Person
    staff: Person
    agency_admin: Person
    agent: Person
    stranger: Person
    agency: Agency

    def grant(self, cap: str = "manager", **kwargs: object) -> AgencyGrant:
        """Owner grants the agency, and the agency admin assigns the agent."""
        grant = svc.create_grant(
            _ctx(self.db, self.tenant_id, self.owner),
            agency_id=self.agency.id,
            role_cap=cap,
            **kwargs,  # type: ignore[arg-type]
        )
        svc.assign_grantee(
            self.db,
            actor=_user(self.db, self.agency_admin),
            grant_id=grant.id,
            user_id=self.agent.user_id,
        )
        self.db.commit()
        return grant

    def url(self, path: str = "/inbox") -> str:
        return f"/api/v1/tenants/{self.tenant_id}{path}"


def _setup(app: FastAPI, db: Session) -> Scenario:
    tenant_id = make_tenant(db, "Client")
    owner = make_person(app, "owner", db=db)
    join(db, tenant_id, owner.user_id, "owner")
    admin = make_person(app, "admin", db=db)
    join(db, tenant_id, admin.user_id, "admin")
    staff = make_person(app, "staff", staff=True, db=db)
    agency_admin = make_person(app, "ag-admin", db=db)
    agent = make_person(app, "ag-member", db=db)
    stranger = make_person(app, "stranger", db=db)
    agency = svc.create_agency(db, actor=_user(db, staff), name="Studio")
    svc.add_agency_member(
        db,
        actor=_user(db, staff),
        agency_id=agency.id,
        user_id=agency_admin.user_id,
        role="agency_admin",
    )
    svc.add_agency_member(
        db, actor=_user(db, agency_admin), agency_id=agency.id, user_id=agent.user_id
    )
    db.commit()
    return Scenario(db, tenant_id, owner, admin, staff, agency_admin, agent, stranger, agency)


def test_nothing_links_an_agency_to_a_client_without_a_grant(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    for person in (s.agency_admin, s.agent):
        assert person.client.get(s.url()).status_code == 404  # existence is not revealed


def test_grant_requires_assignment_and_agency_membership(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    grant = svc.create_grant(
        _ctx(db, s.tenant_id, s.owner), agency_id=s.agency.id, role_cap="manager"
    )
    db.commit()
    # Granted but nobody assigned: the whole agency, including its admin, is still outside.
    for person in (s.agency_admin, s.agent):
        assert person.client.get(s.url()).status_code == 404
    # A person outside the agency cannot be assigned, and a non-admin cannot assign.
    with pytest.raises(ApiError) as outsider_error:
        svc.assign_grantee(
            db, actor=_user(db, s.agency_admin), grant_id=grant.id, user_id=s.stranger.user_id
        )
    assert outsider_error.value.status_code == 422
    with pytest.raises(ApiError) as member_error:
        svc.assign_grantee(db, actor=_user(db, s.agent), grant_id=grant.id, user_id=s.agent.user_id)
    assert member_error.value.status_code == 404
    svc.assign_grantee(
        db, actor=_user(db, s.agency_admin), grant_id=grant.id, user_id=s.agent.user_id
    )
    db.commit()
    assert s.agent.client.get(s.url()).status_code != 404
    # The agency admin was not assigned: still outside.
    assert s.agency_admin.client.get(s.url()).status_code == 404


def test_effective_role_is_the_cap_and_never_team_agency_billing_org(
    v2_app: FastAPI, db: Session
) -> None:
    s = _setup(v2_app, db)
    s.grant(cap="admin")
    client = s.agent.client
    # Admin cap: contact delete is reachable (not the permission refusal).
    reachable = client.delete(s.url(f"/contacts/{uuid4()}"), headers=csrf_headers(client))
    assert FORBIDDEN not in reachable.text
    for path in ("/members", "/invitations", ""):  # "" is org.read, an org.* permission
        response = client.get(s.url(path))
        assert response.status_code == 403 and FORBIDDEN in response.text, path
    patch = client.patch(s.url(""), json={"name": "Hijack"}, headers=csrf_headers(client))
    assert patch.status_code == 403 and FORBIDDEN in patch.text
    for permission in agency_permissions("admin"):
        assert permission == "org.summary" or not permission.startswith(
            ("team.", "agency.", "billing.", "org.")
        )


def test_cap_viewer_cannot_reply_and_owner_cap_is_rejected(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    with pytest.raises(ApiError) as bad_cap:
        svc.create_grant(_ctx(db, s.tenant_id, s.owner), agency_id=s.agency.id, role_cap="owner")
    assert bad_cap.value.status_code == 422
    s.grant(cap="viewer")
    response = s.agent.client.post(
        s.url(f"/conversations/{uuid4()}/resolve"),
        json={},
        headers=csrf_headers(s.agent.client),
    )
    assert response.status_code == 403 and FORBIDDEN in response.text


def test_only_the_real_client_owner_manages_grants(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    for person in (s.admin, s.staff):  # Admin and platform staff are both refused
        with pytest.raises(ApiError) as error:
            svc.create_grant(
                _ctx(db, s.tenant_id, person), agency_id=s.agency.id, role_cap="viewer"
            )
        assert error.value.status_code == 403
    # An agency person acting through a grant cannot grant onward.
    s.grant(cap="admin")
    user = _user(db, s.agent)
    tenant = db.get(Tenant, s.tenant_id)
    assert tenant is not None
    access = resolve_access(db, user=user, tenant=tenant, membership=None)
    assert access is not None and access.via_agency == s.agency.id
    ctx = TenantContext(
        db=db,
        user=user,
        tenant=tenant,
        membership=None,
        org_role=access.org_role,
        permissions=access.permissions,
        via_agency=access.via_agency,
    )
    with pytest.raises(ApiError) as onward:
        svc.create_grant(ctx, agency_id=s.agency.id, role_cap="viewer")
    assert onward.value.status_code == 403


def test_duplicate_active_grant_conflicts_and_revoked_can_be_reissued(
    v2_app: FastAPI, db: Session
) -> None:
    s = _setup(v2_app, db)
    first = svc.create_grant(
        _ctx(db, s.tenant_id, s.owner), agency_id=s.agency.id, role_cap="viewer"
    )
    db.commit()
    with pytest.raises(ApiError) as dup:
        svc.create_grant(_ctx(db, s.tenant_id, s.owner), agency_id=s.agency.id, role_cap="agent")
    assert dup.value.status_code == 409
    svc.revoke_grant(_ctx(db, s.tenant_id, s.owner), grant_id=first.id)
    db.commit()
    again = svc.create_grant(
        _ctx(db, s.tenant_id, s.owner), agency_id=s.agency.id, role_cap="agent"
    )
    db.commit()
    assert again.id != first.id


def test_revocation_is_immediate_and_audited_with_both_ids(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    grant = s.grant()
    assert s.agent.client.get(s.url()).status_code != 404
    svc.revoke_grant(_ctx(db, s.tenant_id, s.owner), grant_id=grant.id)
    db.commit()
    # The assignee's sessions end with the grant (design 6.5) ...
    assert s.agent.client.get(s.url()).status_code == 401
    # ... and a fresh login finds no access either.
    relogin = s.agent.client.post(
        "/api/v1/auth/login", json={"email": s.agent.email, "password": PASSWORD}
    )
    assert relogin.status_code == 200
    assert s.agent.client.get(s.url()).status_code == 404
    events = db.execute(
        select(AuditEvent).where(
            AuditEvent.tenant_id == s.tenant_id, AuditEvent.action.like("agency.%")
        )
    ).scalars()
    by_action = {e.action: e for e in events}
    assert {"agency.grant_created", "agency.grant_assigned", "agency.grant_revoked"} <= set(
        by_action
    )
    revoked = by_action["agency.grant_revoked"]
    assert revoked.actor_user_id == s.owner.user_id
    assert revoked.metadata_json["agency_id"] == str(s.agency.id)


def test_expiry_is_checked_on_every_request(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    grant = s.grant(expires_at=utcnow() + timedelta(hours=1))
    assert s.agent.client.get(s.url()).status_code != 404
    db.execute(
        update(AgencyGrant)
        .where(AgencyGrant.id == grant.id)
        .values(expires_at=utcnow() - timedelta(seconds=1))
    )
    db.commit()
    assert s.agent.client.get(s.url()).status_code == 404
    with pytest.raises(ApiError):
        svc.create_grant(
            _ctx(db, s.tenant_id, s.owner),
            agency_id=s.agency.id,
            role_cap="viewer",
            expires_at=utcnow() - timedelta(days=1),
        )


def test_suspended_agency_and_removed_membership_lose_access(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    s.grant()
    assert s.agent.client.get(s.url()).status_code != 404
    db.execute(update(Agency).where(Agency.id == s.agency.id).values(status="suspended"))
    db.commit()
    assert s.agent.client.get(s.url()).status_code == 404
    db.execute(update(Agency).where(Agency.id == s.agency.id).values(status="active"))
    db.query(AgencyMembership).filter_by(agency_id=s.agency.id, user_id=s.agent.user_id).delete()
    db.commit()
    assert s.agent.client.get(s.url()).status_code == 404


def test_agency_person_cannot_reach_another_client(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    s.grant()
    other = make_tenant(db, "Other")
    assert s.agent.client.get(f"/api/v1/tenants/{other}/inbox").status_code == 404


def test_client_sees_grants_and_other_tenants_grants_are_invisible(
    v2_app: FastAPI, db: Session
) -> None:
    s = _setup(v2_app, db)
    grant = s.grant()
    other = make_tenant(db, "Other")
    other_owner = make_person(v2_app, "other-owner", db=db)
    join(db, other, other_owner.user_id, "owner")
    listing = svc.list_grants(_ctx(db, s.tenant_id, s.admin))  # Admin may view
    assert len(listing) == 1 and listing[0]["agency_name"] == "Studio"
    assert listing[0]["assignees"] == [str(s.agent.user_id)]
    assert svc.list_grants(_ctx(db, other, other_owner)) == []
    manager = make_person(v2_app, "manager", db=db)
    join(db, s.tenant_id, manager.user_id, "manager")
    with pytest.raises(ApiError) as error:
        svc.list_grants(_ctx(db, s.tenant_id, manager))
    assert error.value.status_code == 403
    # An Owner of another organization cannot revoke this organization's grant.
    with pytest.raises(ApiError) as cross:
        svc.revoke_grant(_ctx(db, other, other_owner), grant_id=grant.id)
    assert cross.value.status_code == 404


def test_grant_locations_must_belong_to_the_client(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    other = make_tenant(db, "Other")
    foreign = Location(id=uuid4(), tenant_id=other, name="Elsewhere")
    mine = Location(id=uuid4(), tenant_id=s.tenant_id, name="Here")
    db.add_all([foreign, mine])
    db.commit()
    with pytest.raises(ApiError) as error:
        svc.create_grant(
            _ctx(db, s.tenant_id, s.owner),
            agency_id=s.agency.id,
            role_cap="viewer",
            location_ids=[foreign.id],
        )
    assert error.value.status_code == 404
    svc.create_grant(
        _ctx(db, s.tenant_id, s.owner),
        agency_id=s.agency.id,
        role_cap="viewer",
        location_ids=[mine.id],
    )
    db.commit()


def test_database_refuses_owner_cap_and_cross_tenant_grant_location(
    v2_app: FastAPI, db: Session
) -> None:
    s = _setup(v2_app, db)
    other = make_tenant(db, "Other")
    foreign = Location(id=uuid4(), tenant_id=other, name="Elsewhere")
    db.add(foreign)
    grant = svc.create_grant(
        _ctx(db, s.tenant_id, s.owner), agency_id=s.agency.id, role_cap="viewer"
    )
    db.commit()
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO agency_grant_locations (grant_id, tenant_id, location_id) "
                "VALUES (:g, :t, :l)"
            ),
            {"g": grant.id, "t": s.tenant_id, "l": foreign.id},
        )
    db.rollback()
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE agency_grants SET role_cap='owner' WHERE id=:g"), {"g": grant.id})
    db.rollback()


def test_duplicate_grant_conflict_keeps_the_rest_of_the_request(
    v2_app: FastAPI, db: Session
) -> None:
    s = _setup(v2_app, db)
    svc.create_grant(_ctx(db, s.tenant_id, s.owner), agency_id=s.agency.id, role_cap="viewer")
    db.commit()
    pending = Location(id=uuid4(), tenant_id=s.tenant_id, name="Written earlier in the request")
    db.add(pending)
    with pytest.raises(ApiError) as dup:
        svc.create_grant(_ctx(db, s.tenant_id, s.owner), agency_id=s.agency.id, role_cap="agent")
    assert dup.value.status_code == 409
    db.commit()
    assert db.get(Location, pending.id) is not None


def test_two_grants_with_the_same_cap_resolve_to_the_narrowest_deterministically(
    v2_app: FastAPI, db: Session
) -> None:
    s = _setup(v2_app, db)
    place = Location(id=uuid4(), tenant_id=s.tenant_id, name="Only here")
    db.add(place)
    db.commit()
    second = svc.create_agency(db, actor=_user(db, s.staff), name="Second studio")
    svc.add_agency_member(
        db,
        actor=_user(db, s.staff),
        agency_id=second.id,
        user_id=s.agent.user_id,
        role="agency_admin",
    )
    db.commit()
    unrestricted = s.grant("manager")
    restricted = svc.create_grant(
        _ctx(db, s.tenant_id, s.owner),
        agency_id=second.id,
        role_cap="manager",
        location_ids=[place.id],
    )
    svc.assign_grantee(
        db, actor=_user(db, s.agent), grant_id=restricted.id, user_id=s.agent.user_id
    )
    db.commit()
    for _ in range(3):
        found = svc.active_grant_for(db, user_id=s.agent.user_id, tenant_id=s.tenant_id)
        assert found is not None
        assert found.grant_id == restricted.id != unrestricted.id
        assert found.location_ids == frozenset({place.id})
    # A lower cap still beats a narrower location scope.
    svc.revoke_grant(_ctx(db, s.tenant_id, s.owner), grant_id=unrestricted.id)
    lower = svc.create_grant(
        _ctx(db, s.tenant_id, s.owner), agency_id=s.agency.id, role_cap="viewer"
    )
    svc.assign_grantee(
        db, actor=_user(db, s.agency_admin), grant_id=lower.id, user_id=s.agent.user_id
    )
    db.commit()
    winner = svc.active_grant_for(db, user_id=s.agent.user_id, tenant_id=s.tenant_id)
    assert winner is not None and winner.grant_id == lower.id and winner.role_cap == "viewer"
