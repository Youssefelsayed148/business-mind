"""Privilege escalation attempts (design 10, T-ESC) and grant management. Synthetic data only."""

from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import AgencyGrant, Membership
from tests.helpers import csrf_headers
from tests.identity_helpers import Org, Person, join, make_person
from tests.test_agency_grants import Scenario, _setup, _user
from tests.test_team_management import team_org, url


def patch_role(person: Person, org: Org, target: UUID, role: str) -> Any:
    return person.client.patch(
        url(org, f"/team/members/{target}"),
        json={"role": role},
        headers=csrf_headers(person.client),
    )


def deactivate(person: Person, org: Org, target: UUID) -> Any:
    return person.client.delete(
        url(org, f"/team/members/{target}"), headers=csrf_headers(person.client)
    )


def test_admin_cannot_invite_or_assign_owner_or_admin_but_owner_can(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    admin, owner = org.people["admin"], org.people["owner"]
    for role in ("owner", "admin"):
        refused = admin.client.post(
            url(org, "/team/invitations"),
            json={"email": f"{role}@example.com", "role": role},
            headers=csrf_headers(admin.client),
        )
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "OWNER_REQUIRED"
        assert patch_role(admin, org, org.people["viewer"].user_id, role).status_code == 403
    ok = owner.client.post(
        url(org, "/team/invitations"),
        json={"email": "future-admin@example.com", "role": "admin"},
        headers=csrf_headers(owner.client),
    )
    assert ok.status_code == 202
    assert patch_role(owner, org, org.people["viewer"].user_id, "admin").status_code == 200


def test_admin_cannot_edit_or_remove_anyone_above_manager(v2_app: FastAPI, db: Session) -> None:
    org = team_org(v2_app, db)
    second_admin = make_person(v2_app, "admin2", db=db)
    join(db, org.tenant_id, second_admin.user_id, "admin")
    admin = org.people["admin"]
    for target in (org.people["owner"].user_id, second_admin.user_id):
        assert patch_role(admin, org, target, "viewer").status_code == 403
        assert deactivate(admin, org, target).status_code == 403
    # Nothing changed.
    roles = {
        m.user_id: m.org_role
        for m in db.scalars(select(Membership).where(Membership.tenant_id == org.tenant_id))
    }
    assert roles[org.people["owner"].user_id] == "owner" and roles[second_admin.user_id] == "admin"
    # But an admin does manage everyone below admin.
    assert patch_role(admin, org, org.people["agent"].user_id, "manager").status_code == 200


def test_nobody_edits_their_own_role_or_deactivates_themselves(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    for role in ("owner", "admin"):
        person = org.people[role]
        refused = patch_role(person, org, person.user_id, "viewer")
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "SELF_EDIT"
        assert patch_role(person, org, person.user_id, "owner").status_code == 403
        assert deactivate(person, org, person.user_id).json()["error"]["code"] == "SELF_EDIT"


def test_the_last_owner_cannot_be_demoted_or_removed(v2_app: FastAPI, db: Session) -> None:
    org = team_org(v2_app, db)
    staff = make_person(v2_app, "staff", staff=True, db=db)
    second = make_person(v2_app, "owner2", db=db)
    join(db, org.tenant_id, second.user_id, "owner")
    # Two owners: one may demote the other.
    assert patch_role(org.people["owner"], org, second.user_id, "admin").status_code == 200
    # Now the original is the only Owner. Not even staff can strip or remove them.
    only = org.people["owner"].user_id
    refused = patch_role(staff, org, only, "admin")
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "LAST_OWNER"
    assert deactivate(staff, org, only).json()["error"]["code"] == "LAST_OWNER"
    # Restoring a second owner makes it possible again.
    assert patch_role(org.people["owner"], org, second.user_id, "owner").status_code == 200
    assert patch_role(staff, org, only, "admin").status_code == 200


def test_the_organization_is_never_left_without_an_owner_or_admin(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    staff = make_person(v2_app, "staff", staff=True, db=db)
    db.execute(
        update(Membership)
        .where(
            Membership.tenant_id == org.tenant_id, Membership.user_id == org.people["owner"].user_id
        )
        .values(org_role="manager", role="editor")
    )
    db.commit()  # the only privileged person left is the Admin
    refused = deactivate(staff, org, org.people["admin"].user_id)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "LAST_ADMIN"
    assert patch_role(staff, org, org.people["admin"].user_id, "viewer").status_code == 403
    assert patch_role(staff, org, org.people["admin"].user_id, "owner").status_code == 200


def test_roles_below_admin_have_no_team_or_grant_routes(v2_app: FastAPI, db: Session) -> None:
    org = team_org(v2_app, db)
    for role in ("manager", "agent", "viewer"):
        person = org.people[role]
        for response in (
            person.client.get(url(org, "/team/members")),
            patch_role(person, org, org.people["viewer"].user_id, "agent"),
            deactivate(person, org, org.people["viewer"].user_id),
            person.client.get(url(org, "/agency/grants")),
        ):
            assert response.status_code == 403, (role, response.text)


# --- agency grants through the API ---------------------------------------------------------


def _grant_body(s: Scenario, cap: str = "manager") -> dict[str, Any]:
    return {"agency_id": str(s.agency.id), "role_cap": cap}


def test_owner_creates_lists_and_revokes_a_grant_and_the_agency_admin_assigns(
    v2_app: FastAPI, db: Session
) -> None:
    s = _setup(v2_app, db)
    owner = s.owner
    created = owner.client.post(
        s.url("/agency/grants"), json=_grant_body(s), headers=csrf_headers(owner.client)
    )
    assert created.status_code == 201, created.text
    grant = created.json()
    assert grant["role_cap"] == "manager" and grant["status"] == "active"
    assert grant["assignees"] == [] and grant["location_ids"] == []
    # The agency person is not in yet: nobody is assigned.
    assert s.agent.client.get(s.url("/summary")).status_code == 404
    # Only an admin of the agency assigns, and only people of that agency.
    base = f"/api/v1/agencies/grants/{grant['id']}/assignees"
    body = {"user_id": str(s.agent.user_id)}
    assert (
        s.stranger.client.post(base, json=body, headers=csrf_headers(s.stranger.client)).status_code
        == 404
    )
    assert (
        s.agent.client.post(base, json=body, headers=csrf_headers(s.agent.client)).status_code
        == 404
    )
    outsider_body = {"user_id": str(s.stranger.user_id)}
    refused = s.agency_admin.client.post(
        base, json=outsider_body, headers=csrf_headers(s.agency_admin.client)
    )
    assert refused.status_code == 422
    done = s.agency_admin.client.post(base, json=body, headers=csrf_headers(s.agency_admin.client))
    assert done.status_code == 204
    assert s.agent.client.get(s.url("/summary")).json()["via_agency"] is True
    listed = owner.client.get(s.url("/agency/grants")).json()
    assert [g["id"] for g in listed] == [grant["id"]]
    assert listed[0]["assignees"] == [str(s.agent.user_id)]
    # Revocation is immediate and signs the assignee out.
    revoked = owner.client.delete(
        s.url(f"/agency/grants/{grant['id']}"), headers=csrf_headers(owner.client)
    )
    assert revoked.status_code == 204
    assert s.agent.client.get("/api/v1/auth/me").status_code == 401
    db.expire_all()
    row = db.get(AgencyGrant, UUID(grant["id"]))
    assert row is not None and row.status == "revoked" and row.revoked_by_user_id == owner.user_id


def test_only_the_real_owner_manages_grants_and_admins_may_only_read(
    v2_app: FastAPI, db: Session
) -> None:
    s = _setup(v2_app, db)
    admin = s.admin
    refused = admin.client.post(
        s.url("/agency/grants"), json=_grant_body(s), headers=csrf_headers(admin.client)
    )
    assert refused.status_code == 403
    assert admin.client.get(s.url("/agency/grants")).status_code == 200
    s.grant(cap="viewer")  # an agency grant now exists
    grant_id = db.scalar(select(AgencyGrant.id))
    assert (
        admin.client.delete(
            s.url(f"/agency/grants/{grant_id}"), headers=csrf_headers(admin.client)
        ).status_code
        == 403
    )
    staff_response = s.staff.client.post(
        s.url("/agency/grants"), json=_grant_body(s), headers=csrf_headers(s.staff.client)
    )
    assert staff_response.status_code == 403  # platform staff are not the client's Owner


def test_an_agency_person_cannot_touch_team_or_grants_or_raise_their_own_cap(
    v2_app: FastAPI, db: Session
) -> None:
    s = _setup(v2_app, db)
    grant = s.grant(cap="admin")
    agent = s.agent
    headers = csrf_headers(agent.client)
    assert agent.client.get(s.url("/team/members")).status_code == 403
    assert agent.client.get(s.url("/agency/grants")).status_code == 403
    assert (
        agent.client.post(
            s.url("/agency/grants"), json=_grant_body(s, "admin"), headers=headers
        ).status_code
        == 403
    )
    assert (
        agent.client.delete(s.url(f"/agency/grants/{grant.id}"), headers=headers).status_code == 403
    )
    assert patch_role(agent, Org(s.tenant_id), s.admin.user_id, "viewer").status_code == 403
    invite = agent.client.post(
        s.url("/team/invitations"),
        json={"email": "x@example.com", "role": "viewer"},
        headers=headers,
    )
    assert invite.status_code == 403
    db.expire_all()
    assert db.get(AgencyGrant, grant.id) is not None
    assert db.get(AgencyGrant, grant.id).role_cap == "admin"  # type: ignore[union-attr]


def test_duplicate_active_grant_is_a_conflict_and_owner_cap_is_rejected(
    v2_app: FastAPI, db: Session
) -> None:
    s = _setup(v2_app, db)
    headers = csrf_headers(s.owner.client)
    first = s.owner.client.post(s.url("/agency/grants"), json=_grant_body(s), headers=headers)
    assert first.status_code == 201
    dup = s.owner.client.post(
        s.url("/agency/grants"), json=_grant_body(s, "viewer"), headers=headers
    )
    assert dup.status_code == 409
    owner_cap = s.owner.client.post(
        s.url("/agency/grants"), json=_grant_body(s, "owner"), headers=headers
    )
    assert owner_cap.status_code == 422
    unknown = s.owner.client.post(
        s.url("/agency/grants"),
        json={"agency_id": str(uuid4()), "role_cap": "viewer"},
        headers=headers,
    )
    assert unknown.status_code == 404
    assert _user(db, s.agent) is not None
