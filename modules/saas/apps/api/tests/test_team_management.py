"""Team management (design 6.1, 6.2): invitations v2, new-account acceptance, role change,
deactivate. Synthetic data only (example.com addresses)."""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.security import hash_token
from app.core.config import get_settings
from app.db.base import utcnow
from app.db.models import AuditEvent, Invitation, Membership, Tenant, User
from app.identity.mailer import console_outbox
from tests.conftest import build_test_settings
from tests.helpers import PASSWORD, csrf_headers
from tests.identity_helpers import Org, Person, build_org, make_person

GENERIC = "If this address can be invited, an email was sent."


def team_org(app: FastAPI, db: Session, name: str = "Alpha") -> Org:
    """Five people (one per role) in an organization whose plan has room for more seats."""
    org = build_org(app, db, name)
    db.execute(update(Tenant).where(Tenant.id == org.tenant_id).values(plan_label="business"))
    db.commit()
    return org


def url(org: Org, path: str) -> str:
    return f"/api/v1/tenants/{org.tenant_id}{path}"


def invite(person: Person, org: Org, email: str, role: str = "viewer") -> Any:
    return person.client.post(
        url(org, "/team/invitations"),
        json={"email": email, "role": role},
        headers=csrf_headers(person.client),
    )


def token_of(link_path: str) -> str:
    return link_path.split("token=", 1)[1]


def accept_new(client: TestClient, token: str, password: str = PASSWORD) -> Any:
    return client.post(
        "/api/v1/invitations/accept-new", json={"token": token, "password": password}
    )


def test_invite_answers_the_same_for_every_kind_of_address(v2_app: FastAPI, db: Session) -> None:
    org = team_org(v2_app, db)
    stranger = make_person(v2_app, "elsewhere", db=db)  # has an account, not a member
    answers = []
    for email in (
        f"brand-new-{uuid4().hex[:8]}@example.com",
        stranger.email,
        org.people["viewer"].email,  # already an active member
    ):
        response = invite(org.people["admin"], org, email)
        assert response.status_code == 202, response.text
        answers.append(response)
    assert {r.json()["message"] for r in answers} == {GENERIC}
    # No oracle in status, message or error code (the legacy route said USER_NOT_FOUND).
    assert {r.status_code for r in answers} == {202}
    assert answers[0].json()["link_path"] and answers[1].json()["link_path"]
    assert answers[2].json()["link_path"] is None  # an existing member: no invitation, no mail


def test_invitation_dual_writes_roles_audits_and_mails_from_the_configured_base(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    address = f"manager-{uuid4().hex[:8]}@example.com"
    response = invite(org.people["owner"], org, address, "manager")
    path = response.json()["link_path"]
    row = db.scalar(select(Invitation).where(Invitation.email == address))
    assert row is not None
    assert (row.org_role, row.role, row.new_account, row.location_scope) == (
        "manager",
        "editor",
        True,
        "all",
    )
    assert row.token_hash == hash_token(token_of(path))
    assert row.expires_at - utcnow() <= timedelta(days=7, minutes=1)
    mail = [m for m in console_outbox() if m.to == address][-1]
    assert mail.kind == "invitation"
    assert f"http://localhost:3000/accept-invite?token={token_of(path)}" in mail.body
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "team.invited"))
    assert event is not None and event.metadata_json == {"role": "manager", "new_account": True}
    assert token_of(path) not in str(event.metadata_json)


def test_a_new_invitation_supersedes_the_older_pending_one(v2_app: FastAPI, db: Session) -> None:
    org = team_org(v2_app, db)
    address = f"twice-{uuid4().hex[:8]}@example.com"
    first = token_of(invite(org.people["admin"], org, address).json()["link_path"])
    second = token_of(invite(org.people["admin"], org, address).json()["link_path"])
    anonymous = TestClient(v2_app, raise_server_exceptions=False)
    assert accept_new(anonymous, first).status_code == 409  # revoked by rotation
    assert accept_new(anonymous, second).status_code == 200


def test_new_account_acceptance_creates_the_account_for_the_invited_email_only(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    address = f"newcomer-{uuid4().hex[:8]}@example.com"
    token = token_of(invite(org.people["admin"], org, address, "agent").json()["link_path"])
    anonymous = TestClient(v2_app, raise_server_exceptions=False)
    # The body carries no email: an attacker cannot pick a different address.
    other_email = anonymous.post(
        "/api/v1/invitations/accept-new",
        json={"token": token, "password": PASSWORD, "email": "someone-else@example.com"},
    )
    assert other_email.status_code == 422
    response = accept_new(anonymous, token)
    assert response.status_code == 200, response.text
    assert response.json()["email"] == address
    user = db.scalar(select(User).where(User.email == address))
    assert user is not None and user.is_platform_staff is False
    membership = db.get(Membership, (org.tenant_id, user.id))
    assert membership is not None
    assert (membership.org_role, membership.role, membership.status) == (
        "agent",
        "editor",
        "active",
    )
    assert anonymous.get("/api/v1/auth/me").status_code == 200  # a real session came back
    assert db.scalar(select(AuditEvent.id).where(AuditEvent.action == "team.accepted"))
    # Single use.
    again = accept_new(TestClient(v2_app, raise_server_exceptions=False), token)
    assert again.status_code == 409 and again.json()["error"]["code"] == "INVITATION_USED"


def test_new_account_acceptance_refusals(v2_app: FastAPI, db: Session) -> None:
    org = team_org(v2_app, db)
    anonymous = TestClient(v2_app, raise_server_exceptions=False)
    assert accept_new(anonymous, "x" * 40).status_code == 404
    assert accept_new(anonymous, "short").status_code == 422
    address = f"late-{uuid4().hex[:8]}@example.com"
    token = token_of(invite(org.people["admin"], org, address).json()["link_path"])
    assert accept_new(anonymous, token, "short").status_code == 422
    db.execute(update(Invitation).where(Invitation.email == address).values(expires_at=utcnow()))
    db.commit()
    assert accept_new(anonymous, token).json()["error"]["code"] == "INVITATION_EXPIRED"
    # An account that appeared in the meantime: log in and accept instead.
    other = f"raced-{uuid4().hex[:8]}@example.com"
    other_token = token_of(invite(org.people["admin"], org, other).json()["link_path"])
    db.add(User(id=uuid4(), email=other, password_hash="x"))
    db.commit()
    refused = accept_new(anonymous, other_token)
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "ACCOUNT_EXISTS"


def test_new_account_acceptance_is_rate_limited_per_ip(v2_app: FastAPI, db: Session) -> None:
    anonymous = TestClient(v2_app, raise_server_exceptions=False)
    codes = [accept_new(anonymous, f"{i:040d}").status_code for i in range(12)]
    assert codes[:10] == [404] * 10 and codes[10:] == [429, 429]


def test_existing_account_accepts_with_the_legacy_route_and_keeps_the_new_role(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    person = make_person(v2_app, "existing", db=db)
    link = invite(org.people["owner"], org, person.email, "manager").json()["link_path"]
    accepted = person.client.post(
        "/api/v1/invitations/accept",
        json={"token": token_of(link)},
        headers=csrf_headers(person.client),
    )
    assert accepted.status_code == 200, accepted.text
    membership = db.get(Membership, (org.tenant_id, person.user_id))
    assert membership is not None and membership.org_role == "manager"
    assert membership.role == "editor"
    summary = person.client.get(url(org, "/summary")).json()
    assert summary["role"] == "manager"


def test_role_change_dual_writes_audits_and_revokes_the_targets_sessions(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    target = org.people["viewer"]
    assert target.client.get("/api/v1/auth/me").status_code == 200
    response = org.people["admin"].client.patch(
        url(org, f"/team/members/{target.user_id}"),
        json={"role": "manager"},
        headers=csrf_headers(org.people["admin"].client),
    )
    assert response.status_code == 200, response.text
    assert response.json()["role"] == "manager" and response.json()["email"] == target.email
    db.expire_all()
    membership = db.get(Membership, (org.tenant_id, target.user_id))
    assert membership is not None
    assert (membership.org_role, membership.role) == ("manager", "editor")
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "team.role_changed"))
    assert event is not None and event.metadata_json == {"from": "viewer", "to": "manager"}
    assert event.actor_user_id == org.people["admin"].user_id
    assert target.client.get("/api/v1/auth/me").status_code == 401  # signed out everywhere


def test_deactivate_revokes_membership_invitations_and_sessions(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    target = org.people["agent"]
    pending = invite(org.people["admin"], org, target.email)  # a no-op: already a member
    assert pending.json()["link_path"] is None
    db.add(
        Invitation(
            id=uuid4(),
            tenant_id=org.tenant_id,
            email=target.email,
            role="viewer",
            token_hash=hash_token("old-outstanding-token-value"),
            expires_at=utcnow() + timedelta(days=3),
            created_by=org.people["owner"].user_id,
        )
    )
    db.commit()
    response = org.people["admin"].client.delete(
        url(org, f"/team/members/{target.user_id}"),
        headers=csrf_headers(org.people["admin"].client),
    )
    assert response.status_code == 204
    db.expire_all()
    membership = db.get(Membership, (org.tenant_id, target.user_id))
    assert membership is not None and membership.status == "revoked"
    invitation = db.scalar(select(Invitation).where(Invitation.email == target.email))
    assert invitation is not None and invitation.revoked_at is not None
    assert target.client.get("/api/v1/auth/me").status_code == 401
    listing = org.people["owner"].client.get(url(org, "/team/members")).json()
    assert target.email not in {m["email"] for m in listing}
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "team.deactivated"))
    assert event is not None and event.metadata_json == {"was_role": "agent"}


def test_team_list_shows_the_new_role_vocabulary(v2_app: FastAPI, db: Session) -> None:
    org = team_org(v2_app, db)
    rows = org.people["admin"].client.get(url(org, "/team/members")).json()
    assert {r["email"]: r["role"] for r in rows} == {
        org.people[role].email: role for role in org.people
    }
    assert {r["location_scope"] for r in rows} == {"all"}


def test_location_limited_assignment_is_not_possible_through_the_api(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    owner = org.people["owner"]
    headers = csrf_headers(owner.client)
    assert (
        owner.client.post(
            url(org, "/team/invitations"),
            json={"email": "x@example.com", "role": "agent", "location_scope": "limited"},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        owner.client.patch(
            url(org, f"/team/members/{org.people['agent'].user_id}"),
            json={"role": "agent", "location_scope": "limited"},
            headers=headers,
        ).status_code
        == 422
    )
    assert (
        owner.client.post(
            url(org, "/agency/grants"),
            json={"agency_id": str(uuid4()), "role_cap": "viewer", "location_ids": [str(uuid4())]},
            headers=headers,
        ).status_code
        == 422
    )
    scopes = db.scalars(select(Membership.location_scope)).all()
    assert set(scopes) == {"all"}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/team/members", None),
        ("POST", "/team/invitations", {"email": "a@example.com", "role": "viewer"}),
        ("PATCH", "/team/members/{u}", {"role": "agent"}),
        ("DELETE", "/team/members/{u}", None),
        ("GET", "/agency/grants", None),
        ("POST", "/agency/grants", {"agency_id": str(uuid4()), "role_cap": "viewer"}),
        ("DELETE", "/agency/grants/{u}", None),
    ],
)
def test_flag_off_every_new_route_answers_like_an_unknown_route(
    app: FastAPI, db: Session, method: str, path: str, body: dict[str, Any] | None
) -> None:
    app.dependency_overrides[get_settings] = lambda: build_test_settings()
    org = build_org(app, db, "Alpha")
    owner = org.people["owner"]
    target = url(org, path.replace("{u}", str(uuid4())))
    response = owner.client.request(method, target, json=body, headers=csrf_headers(owner.client))
    assert response.status_code == 404 and response.json() == {"detail": "Not Found"}
    anonymous = TestClient(app, raise_server_exceptions=False)
    assert anonymous.request(method, target, json=body).json() == {"detail": "Not Found"}


def test_flag_off_non_tenant_identity_routes_answer_404(app: FastAPI, db: Session) -> None:
    app.dependency_overrides[get_settings] = lambda: build_test_settings()
    anonymous = TestClient(app, raise_server_exceptions=False)
    accept = anonymous.post(
        "/api/v1/invitations/accept-new", json={"token": "x" * 40, "password": PASSWORD}
    )
    assign = anonymous.post(
        f"/api/v1/agencies/grants/{uuid4()}/assignees", json={"user_id": str(uuid4())}
    )
    assert accept.json() == assign.json() == {"detail": "Not Found"}
    assert accept.status_code == assign.status_code == 404


def test_ids_are_uuids(v2_app: FastAPI, db: Session) -> None:
    org = team_org(v2_app, db)
    response = org.people["owner"].client.delete(
        url(org, "/team/members/not-a-uuid"), headers=csrf_headers(org.people["owner"].client)
    )
    assert response.status_code == 422 and UUID(str(org.tenant_id))
