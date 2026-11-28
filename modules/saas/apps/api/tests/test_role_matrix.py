"""Role matrix over every tenant route x every role (design 5.2), plus flag-off proof.

The golden table below is an independent transcription of the design matrix; it
is compared both with app/identity/roles.py and with the live HTTP behavior.
"""

from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.permissions import TENANT_ROUTE_PERMISSIONS, TENANT_ROUTE_ROLES
from app.identity.roles import (
    ALL_PERMISSIONS,
    GRANT_ROLE_CAPS,
    LEGACY_TO_ORG_ROLE,
    ROLE_PERMISSIONS,
    STAFF_ONLY_PERMISSIONS,
    agency_permissions,
    org_role_of,
)
from tests.helpers import csrf_headers
from tests.identity_helpers import (
    ROLES,
    build_org,
    join,
    make_person,
    make_tenant,
)
from tests.test_agency_grants import _setup
from tests.test_tenant_route_matrix import FLAG_ON_ONLY_ROUTES

FORBIDDEN_MESSAGE = "You do not have permission for this action."
MEMBERSHIP_ONLY = "Inbox actions require an active tenant membership."
OWN, A, M, G, V = "owner", "admin", "manager", "agent", "viewer"
ALL5 = {OWN, A, M, G, V}

GOLDEN: dict[str, set[str]] = {
    "inbox.read": ALL5,
    "contacts.read": ALL5,
    "analytics.read": ALL5,
    "channels.read": ALL5,
    "org.read": ALL5,
    "org.summary": ALL5,
    "bots.read": ALL5,
    "knowledge.read": ALL5,
    "campaigns.read": ALL5,
    "inbox.reply": {OWN, A, M, G},
    "contacts.write": {OWN, A, M, G},
    "contacts.delete": {OWN, A},
    "contacts.merge": {OWN, A},
    "contacts.stages": {OWN, A},
    "conversations.delete": {OWN, A},
    "contacts.export": {OWN, A},
    "org.customer_links": {OWN, A},
    "org.customer_erase": {OWN, A},
    "analytics.export": {OWN, A},
    "data.export": {OWN, A},
    "knowledge.write": {OWN, A, M},
    "bots.configure": set(),
    "rag.settings": set(),
    "org.delete": set(),
    "campaigns.manage": {OWN, A, M},
    "campaigns.run": {OWN, A},
    "templates.manage": {OWN, A},
    "channels.connect": {OWN, A},
    "channels.disconnect": {OWN, A},
    "channels.hard_delete": {OWN},
    "team.read": {OWN, A},
    "team.manage": {OWN, A},
    "team.manage_admins": {OWN},
    "agency.view": {OWN, A},
    "agency.manage": {OWN},
    "audit.view": {OWN, A},
    "data.erase": {OWN, A},
    "org.settings": {OWN, A},
    "billing.view": {OWN},
    "billing.manage": {OWN},
}


def _live_tenant_routes(app: FastAPI) -> set[tuple[str, str]]:
    """Tenant routes as the running app exposes them (FastAPI wraps included routers,
    so the schema is the reliable enumeration)."""
    found: set[tuple[str, str]] = set()
    for path, operations in app.openapi()["paths"].items():
        if path.startswith("/api/v1/tenants/{tenant_id}"):
            for method in operations:
                if method.upper() not in {"HEAD", "OPTIONS"}:
                    found.add((method.upper(), path))
    return found


def test_every_live_tenant_route_has_a_reviewed_permission(app: FastAPI) -> None:
    live = _live_tenant_routes(app)
    declared = {k for k in TENANT_ROUTE_PERMISSIONS if k != ("POST", "/api/v1/tenants")}
    assert live == declared, (live - declared, declared - live)
    assert set(TENANT_ROUTE_PERMISSIONS) == set(TENANT_ROUTE_ROLES)
    unknown = set(TENANT_ROUTE_PERMISSIONS.values()) - set(GOLDEN) - {"authenticated"}
    assert not unknown, unknown


def test_role_table_matches_the_golden_design_matrix() -> None:
    assert set(GOLDEN) == set(ALL_PERMISSIONS)
    for permission, allowed in GOLDEN.items():
        actual = {role for role in ROLES if permission in ROLE_PERMISSIONS[role]}
        assert actual == allowed, (permission, actual, allowed)
    assert STAFF_ONLY_PERMISSIONS == {"bots.configure", "rag.settings", "org.delete"}
    # Roles only ever add abilities as they go up (no sideways surprises).
    chain = [ROLE_PERMISSIONS[r] for r in (V, G, M, A, OWN)]
    for lower, higher in zip(chain, chain[1:], strict=False):
        assert lower < higher


def _legacy_allows(role: str, minimum: str) -> bool:
    if minimum in ("platform_staff_only", "authenticated"):
        return False
    return {"viewer": 1, "editor": 2, "admin": 3}[role] >= {"viewer": 1, "editor": 2, "admin": 3}[
        minimum
    ]


def test_no_legacy_ability_is_lost_and_only_knowledge_widens() -> None:
    widened: set[tuple[str, str, str]] = set()
    for key, permission in TENANT_ROUTE_PERMISSIONS.items():
        if permission == "authenticated":
            continue
        minimum = TENANT_ROUTE_ROLES[key]
        for legacy in ("viewer", "editor", "admin"):
            before = _legacy_allows(legacy, minimum)
            after = permission in ROLE_PERMISSIONS[LEGACY_TO_ORG_ROLE[legacy]]
            assert not (before and not after), (key, legacy, "lost")
            if after and not before:
                widened.add((permission, legacy, minimum))
    assert {p for p, _, _ in widened} <= {"knowledge.read", "knowledge.write"}, widened


def test_org_role_mapping_never_escalates() -> None:
    assert LEGACY_TO_ORG_ROLE == {"viewer": "viewer", "editor": "agent", "admin": "admin"}
    assert org_role_of("editor", None) == "agent"
    assert org_role_of("viewer", "manager") == "manager"  # explicit value wins
    for bad in ("owner", "manager", "superuser"):
        try:
            org_role_of(bad, None)
        except ValueError:
            continue
        raise AssertionError(f"legacy role {bad!r} must not be mapped")


# Server-sent streams never finish for a caller who is allowed in, so those routes
# are only called for roles expected to be refused (the table test covers the rest).
STREAMING = {
    ("GET", "/api/v1/tenants/{tenant_id}/inbox/events"),
    ("POST", "/api/v1/tenants/{tenant_id}/bots/{bot_id}/playground/messages/stream"),
}


def _url(path: str, tenant_id: UUID) -> str:
    out = path.replace("{tenant_id}", str(tenant_id)).replace("{tag}", "tag")
    while "{" in out:
        start = out.index("{")
        out = out[:start] + str(uuid4()) + out[out.index("}") + 1 :]
    return out


def _call(person: Any, method: str, url: str) -> Any:
    headers = csrf_headers(person.client) if method != "GET" else {}
    return person.client.request(method, url, json={} if method != "GET" else None, headers=headers)


def _denied_by_permission(response: Any) -> bool:
    return response.status_code == 403 and FORBIDDEN_MESSAGE in response.text


# A caller the table allows must not be turned away by an older handler check, nor crash it.
LEGACY_REFUSALS = ("Only platform staff", "role or higher")


def _broken_for_allowed_caller(response: Any) -> bool:
    return response.status_code == 500 or any(text in response.text for text in LEGACY_REFUSALS)


def _with_data_flag(app: FastAPI) -> None:
    """The Phase 5 people routes answer 404 until DATA_UNIFICATION_ENABLED is on (before any role
    check, like every flagged route), so the matrix turns it on next to identity v2."""
    from tests.conftest import build_test_settings

    app.dependency_overrides[get_settings] = lambda: build_test_settings(
        identity_v2_enabled=True, data_unification_enabled=True
    )


def test_http_role_matrix_every_route_every_role(v2_app: FastAPI, db: Session) -> None:
    _with_data_flag(v2_app)
    org = build_org(v2_app, db, "Alpha")
    other = build_org(v2_app, db, "Beta")
    staff = make_person(v2_app, "staff", staff=True, db=db)
    outsider = other.people[OWN]  # a real Owner, but of a different organization
    mismatches: list[str] = []
    for (method, path), permission in sorted(TENANT_ROUTE_PERMISSIONS.items()):
        if permission == "authenticated":
            continue
        url = _url(path, org.tenant_id)
        for role in ROLES:
            expected_allow = role in GOLDEN[permission]
            if (method, path) in STREAMING and expected_allow:
                continue
            response = _call(org.people[role], method, url)
            denied = _denied_by_permission(response)
            if response.status_code == 401 or denied == expected_allow:
                mismatches.append(f"{role} {method} {path}: {response.status_code}")
            elif expected_allow and _broken_for_allowed_caller(response):
                mismatches.append(f"broken {role} {method} {path}: {response.status_code}")
        if (method, path) not in STREAMING:
            staff_response = _call(staff, method, url)
            if _denied_by_permission(staff_response) or staff_response.status_code == 401:
                mismatches.append(f"staff {method} {path}: {staff_response.status_code}")
        # Another organization's Owner sees a 404 everywhere (existence not revealed).
        if _call(outsider, method, url).status_code != 404:
            mismatches.append(f"outsider {method} {path}")
    assert not mismatches, "\n".join(mismatches[:40])


def test_http_role_matrix_every_route_every_agency_cap(v2_app: FastAPI, db: Session) -> None:
    _with_data_flag(v2_app)
    mismatches: list[str] = []
    for cap in GRANT_ROLE_CAPS:
        scenario = _setup(v2_app, db)
        scenario.grant(cap=cap)
        allowed_permissions = agency_permissions(cap)
        for (method, path), permission in sorted(TENANT_ROUTE_PERMISSIONS.items()):
            if permission == "authenticated":
                continue
            allowed = permission in allowed_permissions
            if (method, path) in STREAMING and allowed:
                continue
            response = _call(scenario.agent, method, _url(path, scenario.tenant_id))
            if not allowed:
                if not _denied_by_permission(response):
                    mismatches.append(f"{cap} {method} {path}: {response.status_code}")
                continue
            # Taking over and replying need a membership row (database foreign keys).
            if MEMBERSHIP_ONLY in response.text:
                if permission != "inbox.reply":
                    mismatches.append(f"membership {cap} {method} {path}")
                continue
            if (
                response.status_code == 401
                or _denied_by_permission(response)
                or _broken_for_allowed_caller(response)
            ):
                mismatches.append(f"{cap} {method} {path}: {response.status_code}")
    assert not mismatches, "\n".join(mismatches[:60])


def test_anonymous_gets_401_on_every_tenant_route(v2_app: FastAPI, db: Session) -> None:
    _with_data_flag(v2_app)
    from fastapi.testclient import TestClient

    tenant_id = make_tenant(db)
    anonymous = TestClient(v2_app, raise_server_exceptions=False)
    for method, path in sorted(TENANT_ROUTE_PERMISSIONS):
        if path == "/api/v1/tenants":
            continue
        response = anonymous.request(method, _url(path, tenant_id))
        assert response.status_code == 401, (method, path, response.status_code)


def test_flag_off_ignores_org_role_flag_on_honors_it(app: FastAPI, db: Session) -> None:
    """A legacy viewer holding org_role=owner is still a viewer until the flag is on."""
    tenant_id = make_tenant(db)
    person = make_person(app, "promoted", db=db)
    join(db, tenant_id, person.user_id, "owner")
    # Legacy column says admin for owner; force the legacy role to viewer.
    from sqlalchemy import update

    from app.db.models import Membership

    db.execute(
        update(Membership)
        .where(Membership.user_id == person.user_id)
        .values(role="viewer", org_role="owner")
    )
    db.commit()
    url = f"/api/v1/tenants/{tenant_id}"
    # Same application object: toggle the settings override explicitly.
    from app.core.config import get_settings
    from tests.conftest import build_test_settings

    app.dependency_overrides[get_settings] = lambda: build_test_settings()
    off = person.client.patch(url, json={"name": "X"}, headers=csrf_headers(person.client))
    assert off.status_code == 403 and "requires the admin role" in off.text
    app.dependency_overrides[get_settings] = lambda: build_test_settings(identity_v2_enabled=True)
    on = person.client.patch(url, json={"name": "X"}, headers=csrf_headers(person.client))
    assert not _denied_by_permission(on) and on.status_code != 403


def test_flag_off_legacy_responses_for_every_route_and_legacy_role(
    app: FastAPI, db: Session
) -> None:
    """Flag off: the status of each route matches the legacy minimum for viewer/editor/admin."""
    tenant_id = make_tenant(db)
    people = {}
    for legacy in ("viewer", "editor", "admin"):
        person = make_person(app, f"legacy-{legacy}", db=db)
        role = {"viewer": "viewer", "editor": "agent", "admin": "admin"}[legacy]
        join(db, tenant_id, person.user_id, role, org_role=None)  # no org_role at all
        people[legacy] = person
    mismatches: list[str] = []
    for (method, path), minimum in sorted(TENANT_ROUTE_ROLES.items()):
        if (method, path) in FLAG_ON_ONLY_ROUTES:
            continue  # identity routes do not exist flag off; their 404s are asserted elsewhere
        if minimum == "authenticated" or ((method, path) in STREAMING):
            continue  # streams never finish for an allowed caller
        url = _url(path, tenant_id)
        for legacy, person in people.items():
            response = _call(person, method, url)
            legacy_denied = response.status_code == 403 and (
                "requires the" in response.text or "Only platform staff" in response.text
            )
            if legacy_denied == _legacy_allows(legacy, minimum):
                mismatches.append(f"{legacy} {method} {path} -> {response.status_code}")
    assert not mismatches, "\n".join(mismatches[:40])
