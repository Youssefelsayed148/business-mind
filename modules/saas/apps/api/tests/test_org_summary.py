"""GET /tenants/{id}/summary (permission org.summary, owner decision on PR B)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.identity import agency as svc
from app.identity.roles import ROLE_PERMISSIONS, agency_permissions
from tests.conftest import build_test_settings
from tests.helpers import PASSWORD, csrf_headers
from tests.identity_helpers import ROLES, build_org
from tests.test_agency_grants import FORBIDDEN, _ctx, _setup


def test_every_role_gets_the_same_narrow_payload(v2_app: FastAPI, db: Session) -> None:
    org = build_org(v2_app, db, "Alpha")
    for role in ROLES:
        response = org.people[role].client.get(f"/api/v1/tenants/{org.tenant_id}/summary")
        assert response.status_code == 200, (role, response.text)
        assert response.json() == {
            "organization_id": str(org.tenant_id),
            "organization_name": "Alpha",
            "role": role,
            "role_cap": None,
            "via_agency": False,
        }


def test_other_organizations_get_404_and_anonymous_gets_401(v2_app: FastAPI, db: Session) -> None:
    alpha = build_org(v2_app, db, "Alpha")
    beta = build_org(v2_app, db, "Beta")
    url = f"/api/v1/tenants/{alpha.tenant_id}/summary"
    assert beta.people["owner"].client.get(url).status_code == 404
    assert TestClient(v2_app, raise_server_exceptions=False).get(url).status_code == 401


def test_agency_user_gets_summary_but_no_other_org_permission(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    s.grant(cap="admin")
    client = s.agent.client
    body = client.get(s.url("/summary"))
    assert body.status_code == 200
    assert body.json() == {
        "organization_id": str(s.tenant_id),
        "organization_name": "Client",
        "role": "admin",
        "role_cap": "admin",
        "via_agency": True,
    }
    # Still no org.read, org.settings or anything else under org.*.
    assert client.get(s.url("")).status_code == 403
    patch = client.patch(s.url(""), json={"name": "Hijack"}, headers=csrf_headers(client))
    assert patch.status_code == 403 and FORBIDDEN in patch.text
    for cap in ("admin", "manager", "agent", "viewer"):
        held = {p for p in agency_permissions(cap) if p.startswith("org.")}
        assert held == {"org.summary"}, cap


def test_org_summary_is_held_by_every_role_and_is_the_only_agency_exception() -> None:
    assert all("org.summary" in ROLE_PERMISSIONS[role] for role in ROLES)
    assert "org.read" not in agency_permissions("viewer")


def test_agency_user_gets_404_for_another_organization(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    s.grant(cap="viewer")
    other = build_org(v2_app, db, "Elsewhere")
    assert s.agent.client.get(f"/api/v1/tenants/{other.tenant_id}/summary").status_code == 404


def test_revoked_grant_loses_the_summary(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    grant = s.grant(cap="viewer")
    assert s.agent.client.get(s.url("/summary")).status_code == 200
    svc.revoke_grant(_ctx(db, s.tenant_id, s.owner), grant_id=grant.id)
    db.commit()
    assert s.agent.client.get(s.url("/summary")).status_code == 401  # sessions ended
    relogin = s.agent.client.post(
        "/api/v1/auth/login", json={"email": s.agent.email, "password": PASSWORD}
    )
    assert relogin.status_code == 200
    assert s.agent.client.get(s.url("/summary")).status_code == 404


def test_flag_off_answers_exactly_like_an_unknown_route(app: FastAPI, db: Session) -> None:
    app.dependency_overrides[get_settings] = lambda: build_test_settings()
    org = build_org(app, db, "Alpha")
    person = org.people["owner"]
    summary = person.client.get(f"/api/v1/tenants/{org.tenant_id}/summary")
    unknown = person.client.get(f"/api/v1/tenants/{org.tenant_id}/summary-not-a-route")
    assert summary.status_code == unknown.status_code == 404
    assert summary.json() == unknown.json() == {"detail": "Not Found"}
    # Anonymous callers and malformed ids also see the unknown-route answer.
    anonymous = TestClient(app, raise_server_exceptions=False)
    assert anonymous.get(f"/api/v1/tenants/{org.tenant_id}/summary").json() == {
        "detail": "Not Found"
    }
    assert anonymous.get("/api/v1/tenants/not-a-uuid/summary").json() == {"detail": "Not Found"}
