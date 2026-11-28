"""The server-side Many proxy (Phase 4A, P1). A fake Many answers; no network is used.

Covers: flag off, authentication and CSRF, the allowlist (deny by default), the role matrix for
every allowlisted route, tenant isolation, what is and is not forwarded, token reuse, and failure
mapping. Synthetic data only.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings, validate_startup_settings
from app.db.models import AuditEvent, Tenant
from app.identity import many_proxy, many_routes
from app.identity.roles import ROLE_PERMISSIONS
from tests.helpers import csrf_headers
from tests.identity_helpers import ROLES, Person, build_org, make_person
from tests.test_phase3_review_fixes import _limit_to_a_new_location
from tests.test_sso_issue import sso_settings

MANY_URL = "http://many.test"


def proxy_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "identity_v2_enabled": True,
        "many_proxy_enabled": True,
        "many_api_base_url": MANY_URL,
    }
    values.update(overrides)
    return sso_settings(**values)


@dataclass
class FakeMany:
    calls: list[dict[str, Any]] = field(default_factory=list)
    exchanges: int = 0
    plan: list[many_proxy.ManyResponse | Exception] = field(default_factory=list)

    def __call__(
        self,
        settings: Settings,
        method: str,
        path_and_query: str,
        headers: dict[str, str],
        body: bytes | None,
    ) -> many_proxy.ManyResponse:
        call = {"method": method, "path": path_and_query, "headers": headers, "body": body}
        self.calls.append(call)
        if path_and_query == "/auth/sso/exchange":
            self.exchanges += 1
            payload = {"access_token": f"many-token-{self.exchanges}", "expires_in": 600}
            return many_proxy.ManyResponse(
                200, {"content-type": "application/json"}, json.dumps(payload).encode()
            )
        if self.plan:
            item = self.plan.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return many_proxy.ManyResponse(200, {"content-type": "application/json"}, b'{"ok":true}')

    @property
    def forwarded(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c["path"] != "/auth/sso/exchange"]


@pytest.fixture
def many(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeMany]:
    fake = FakeMany()
    monkeypatch.setattr(many_proxy, "send_to_many", fake)
    many_proxy.clear_token_cache()
    yield fake
    many_proxy.clear_token_cache()


@pytest.fixture
def proxy_app(v2_app: FastAPI) -> FastAPI:
    v2_app.dependency_overrides[get_settings] = lambda: proxy_settings()
    return v2_app


def _map(db: Session, tenant_id: UUID) -> UUID:
    workspace = uuid4()
    db.execute(update(Tenant).where(Tenant.id == tenant_id).values(many_workspace_id=workspace))
    db.commit()
    return workspace


def _call(
    person: Person,
    method: str,
    path: str,
    *,
    body: Any = None,
    headers: dict[str, str] | None = None,
) -> Any:
    merged = {} if method == "GET" else csrf_headers(person.client)
    merged.update(headers or {})
    return person.client.request(method, path, json=body, headers=merged)


def _org(tenant_id: UUID, many_path: str) -> str:
    return f"/api/v1/many/orgs/{tenant_id}/{many_path}"


def _concrete(template: str) -> str:
    parts = []
    for segment in template.strip("/").split("/"):
        parts.append(str(uuid4()) if segment.startswith("{") else segment)
    return "/".join(parts)


def _unverified(token: str) -> dict[str, Any]:
    payload = token.split(".")[1]
    claims: dict[str, Any] = json.loads(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    )
    return claims


# --- off, unauthenticated, CSRF ------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"many_proxy_enabled": False},
        {"identity_v2_enabled": False},
        {"sso_issuer_enabled": False},
    ],
)
def test_off_answers_like_an_unknown_route(
    v2_app: FastAPI, db: Session, many: FakeMany, overrides: dict[str, Any]
) -> None:
    org = build_org(v2_app, db, "Alpha")
    _map(db, org.tenant_id)
    v2_app.dependency_overrides[get_settings] = lambda: proxy_settings(**overrides)
    owner = org.people["owner"]
    for path in (_org(org.tenant_id, "whatsapp/accounts"), "/api/v1/many/staff/stats/overview"):
        response = _call(owner, "GET", path)
        assert response.status_code == 404 and response.json() == {"detail": "Not Found"}, (
            response.text
        )
    assert many.calls == []


def test_unauthenticated_and_missing_csrf_are_refused(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    org = build_org(proxy_app, db, "Alpha")
    _map(db, org.tenant_id)
    owner = org.people["owner"]
    anonymous = Person(client=proxy_app_client(proxy_app), user_id=owner.user_id, email=owner.email)
    assert anonymous.client.get(_org(org.tenant_id, "whatsapp/accounts")).status_code == 401
    refused = owner.client.post(_org(org.tenant_id, "whatsapp/contacts/import"), json={})
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "CSRF_MISSING"
    assert many.calls == []


def proxy_app_client(app: FastAPI) -> Any:
    from fastapi.testclient import TestClient

    return TestClient(app)


# --- the allowlist is deny by default --------------------------------------------------------

DENIED_PATHS = [
    "auth/me",
    "auth/login",
    "auth/sso/exchange",
    "api/saas/messages",
    "saas/messages",
    "webhooks/meta",
    "meta/callback",
    "meta/compliance/facebook/deauthorize",
    "health",
    "privacy/contact-erasure/whatsapp/x",
    "public/whatsapp/opt-in/abc",
    "workspaces/me",
    "instagram/accounts",  # global routes are not reachable through an organization path
    "whatsapp",
    "whatsapp/accounts/",
    "whatsapp//accounts",
    "whatsapp/%2e%2e/auth/me",
    "whatsapp/accounts/%2e%2e%2fauth%2fme",
    "whatsapp/accounts/a%2fb",
    "whatsapp/accounts/..%5cauth",
    "WHATSAPP/accounts",
    "whatsapp/accounts%00",
]


@pytest.mark.parametrize("path", DENIED_PATHS)
def test_paths_outside_the_allowlist_never_reach_many(
    proxy_app: FastAPI, db: Session, many: FakeMany, path: str
) -> None:
    org = build_org(proxy_app, db, "Alpha")
    _map(db, org.tenant_id)
    staff = make_person(proxy_app, "staff", staff=True, db=db)
    for person in (org.people["owner"], staff):
        for method in ("GET", "POST", "PATCH", "DELETE"):
            response = _call(person, method, _org(org.tenant_id, path))
            assert response.status_code in (404, 422), (method, path, response.status_code)
    assert many.forwarded == []


@pytest.mark.parametrize(
    "path", ["auth/me", "api/saas/messages", "webhooks/meta", "stats/%2e%2e/auth/me", "campaigns/"]
)
def test_staff_paths_outside_the_allowlist_never_reach_many(
    proxy_app: FastAPI, db: Session, many: FakeMany, path: str
) -> None:
    staff = make_person(proxy_app, "staff", staff=True, db=db)
    for method in ("GET", "POST", "PATCH", "DELETE"):
        assert _call(staff, method, f"/api/v1/many/staff/{path}").status_code in (404, 422)
    assert many.forwarded == []


def test_the_allowlist_never_contains_a_forbidden_prefix_or_an_unsafe_template() -> None:
    for route in many_routes.ROUTES:
        template = route.template
        assert template.startswith("/") and not template.endswith("/") and "//" not in template
        assert route.method in {"GET", "POST", "PATCH", "DELETE"}
        for prefix in many_routes.NEVER_PREFIXES:
            assert not (template == prefix or template.startswith(prefix + "/")), (route, prefix)
        assert (route.audience == many_routes.GLOBAL) == (route.permission is None)
        if route.audience == many_routes.GLOBAL:
            assert route.staff_only
    keys = [(r.method, r.template, r.audience) for r in many_routes.ROUTES]
    assert len(keys) == len(set(keys))
    known = set(ROLE_PERMISSIONS["owner"])
    for route in many_routes.ROUTES:
        assert route.permission is None or route.permission in known, route


# --- role matrix: every allowlisted org route, every role ------------------------------------


def test_every_org_route_follows_the_permission_for_every_role(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    org = build_org(proxy_app, db, "Alpha")
    _map(db, org.tenant_id)
    failures: list[str] = []
    for route in many_routes.ROUTES:
        if route.audience != many_routes.ORG:
            continue
        for role in ROLES:
            before = len(many.forwarded)
            response = _call(
                org.people[role], route.method, _org(org.tenant_id, _concrete(route.template))
            )
            allowed = not route.staff_only and route.permission in ROLE_PERMISSIONS[role]
            sent = len(many.forwarded) - before
            if route.staff_only:
                ok = response.status_code == 404 and sent == 0
            elif allowed:
                ok = response.status_code == 200 and sent == 1
            else:
                ok = response.status_code == 403 and sent == 0
            if not ok:
                failures.append(
                    f"{role} {route.method} {route.template}: {response.status_code}, forwarded {sent}"
                )
    assert not failures, "\n".join(failures[:20])


def test_staff_may_use_every_org_route_and_every_global_route(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    org = build_org(proxy_app, db, "Alpha")
    workspace = _map(db, org.tenant_id)
    staff = make_person(proxy_app, "staff", staff=True, db=db)
    for route in many_routes.ROUTES:
        path = (
            _org(org.tenant_id, _concrete(route.template))
            if route.audience == many_routes.ORG
            else f"/api/v1/many/staff/{_concrete(route.template)}"
        )
        response = _call(staff, route.method, path)
        assert response.status_code == 200, (route, response.text)
        sent = many.forwarded[-1]
        header = sent["headers"].get("x-workspace-id")
        assert header == (str(workspace) if route.audience == many_routes.ORG else None)


def test_clients_never_reach_global_routes(proxy_app: FastAPI, db: Session, many: FakeMany) -> None:
    org = build_org(proxy_app, db, "Alpha")
    _map(db, org.tenant_id)
    for route in many_routes.ROUTES:
        if route.audience != many_routes.GLOBAL:
            continue
        for role in ROLES:
            response = _call(
                org.people[role], route.method, f"/api/v1/many/staff/{_concrete(route.template)}"
            )
            assert response.status_code == 403, (role, route)
    assert many.forwarded == []


# --- isolation --------------------------------------------------------------------------------


def test_a_member_of_one_organization_cannot_reach_another(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    a, b = build_org(proxy_app, db, "A"), build_org(proxy_app, db, "B")
    _map(db, a.tenant_id)
    _map(db, b.tenant_id)
    stranger = make_person(proxy_app, "nobody", db=db)
    for person in (a.people["owner"], stranger):
        assert _call(person, "GET", _org(b.tenant_id, "whatsapp/accounts")).status_code == 404
    assert _call(a.people["owner"], "GET", _org(uuid4(), "whatsapp/accounts")).status_code == 404
    assert many.calls == []
    assert (
        _call(b.people["owner"], "GET", _org(b.tenant_id, "whatsapp/accounts")).status_code == 200
    )


def test_unmapped_and_archived_organizations_are_not_found(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    org = build_org(proxy_app, db, "Alpha")
    owner = org.people["owner"]
    assert (
        _call(owner, "GET", _org(org.tenant_id, "whatsapp/accounts")).status_code == 404
    )  # not mapped
    _map(db, org.tenant_id)
    assert _call(owner, "GET", _org(org.tenant_id, "whatsapp/accounts")).status_code == 200
    db.execute(update(Tenant).where(Tenant.id == org.tenant_id).values(status="archived"))
    db.commit()
    assert _call(owner, "GET", _org(org.tenant_id, "whatsapp/accounts")).status_code == 404


def test_a_location_limited_member_gets_no_many_access(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    org = build_org(proxy_app, db, "Alpha")
    _map(db, org.tenant_id)
    admin = org.people["admin"]
    _limit_to_a_new_location(db, org.tenant_id, admin.user_id)
    response = _call(admin, "GET", _org(org.tenant_id, "whatsapp/accounts"))
    assert (
        response.status_code == 403
        and response.json()["error"]["code"] == "LOCATION_SCOPE_UNSUPPORTED"
    )
    assert many.calls == []


# --- what is forwarded -----------------------------------------------------------------------


def test_only_the_server_minted_credentials_are_forwarded(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    org = build_org(proxy_app, db, "Alpha")
    workspace = _map(db, org.tenant_id)
    owner = org.people["owner"]
    response = _call(
        owner,
        "GET",
        _org(org.tenant_id, "whatsapp/accounts") + "?limit=5",
        headers={
            "Authorization": "Bearer browser-supplied",
            "X-Workspace-Id": str(uuid4()),
            "X-Forwarded-For": "6.6.6.6",
            "Accept": "application/json",
        },
    )
    assert response.status_code == 200 and response.json() == {"ok": True}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]
    sent = many.forwarded[0]
    assert sent["path"] == "/whatsapp/accounts?limit=5" and sent["method"] == "GET"
    assert sent["headers"]["authorization"] == "Bearer many-token-1"
    assert sent["headers"]["x-workspace-id"] == str(workspace)
    assert set(sent["headers"]) <= {"accept", "authorization", "x-workspace-id", "content-type"}
    exchange = many.calls[0]
    assert exchange["path"] == "/auth/sso/exchange"
    claims = _unverified(json.loads(exchange["body"])["assertion"])
    assert (
        claims["scope"] == "client"
        and claims["org"] == str(org.tenant_id)
        and claims["role"] == "owner"
    )


def test_staff_acting_in_an_organization_use_the_staff_scope_with_that_workspace(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    org = build_org(proxy_app, db, "Alpha")
    workspace = _map(db, org.tenant_id)
    staff = make_person(proxy_app, "staff", staff=True, db=db)
    assert _call(staff, "GET", _org(org.tenant_id, "whatsapp/accounts")).status_code == 200
    claims = _unverified(json.loads(many.calls[0]["body"])["assertion"])
    assert claims["scope"] == "staff" and claims["org"] == str(org.tenant_id)
    assert claims["workspace"] == str(workspace) and "role" not in claims
    assert many.forwarded[0]["headers"]["x-workspace-id"] == str(workspace)


def test_the_request_body_is_forwarded_and_writes_are_audited(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    org = build_org(proxy_app, db, "Alpha")
    _map(db, org.tenant_id)
    admin = org.people["admin"]
    assert _call(admin, "GET", _org(org.tenant_id, "whatsapp/contacts")).status_code == 200
    assert db.scalar(select(AuditEvent.id).where(AuditEvent.action == "many.proxy_write")) is None
    response = _call(
        admin, "POST", _org(org.tenant_id, "whatsapp/campaigns"), body={"name": "Spring"}
    )
    assert response.status_code == 200
    sent = many.forwarded[-1]
    assert (
        json.loads(sent["body"]) == {"name": "Spring"}
        and sent["headers"]["content-type"] == "application/json"
    )
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "many.proxy_write"))
    assert (
        event is not None
        and event.tenant_id == org.tenant_id
        and event.actor_user_id == admin.user_id
    )
    assert event.target_id == "/whatsapp/campaigns"


def test_oversized_bodies_and_bad_queries_are_refused_before_anything_is_sent(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    proxy_app.dependency_overrides[get_settings] = lambda: proxy_settings(
        many_proxy_max_body_bytes=1024
    )
    org = build_org(proxy_app, db, "Alpha")
    _map(db, org.tenant_id)
    admin = org.people["admin"]
    big = _call(admin, "POST", _org(org.tenant_id, "whatsapp/campaigns"), body={"x": "y" * 4000})
    assert big.status_code == 413
    assert _call(
        admin, "GET", _org(org.tenant_id, "whatsapp/accounts") + "?a=%0d%0aX-Evil:1"
    ).status_code in (200, 422)
    long_query = _call(admin, "GET", _org(org.tenant_id, "whatsapp/accounts") + "?a=" + "b" * 3000)
    assert long_query.status_code == 422
    assert all("\r" not in c["path"] and "\n" not in c["path"] for c in many.calls)


# --- tokens and failures ----------------------------------------------------------------------


def test_the_many_token_is_reused_and_follows_the_role(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    org = build_org(proxy_app, db, "Alpha")
    _map(db, org.tenant_id)
    owner, admin = org.people["owner"], org.people["admin"]
    for _ in range(3):
        assert _call(owner, "GET", _org(org.tenant_id, "whatsapp/accounts")).status_code == 200
    assert many.exchanges == 1
    assert _call(admin, "GET", _org(org.tenant_id, "whatsapp/accounts")).status_code == 200
    assert many.exchanges == 2  # another person, another token
    tokens = {c["headers"]["authorization"] for c in many.forwarded}
    assert tokens == {"Bearer many-token-1", "Bearer many-token-2"}


def test_a_token_many_refuses_is_exchanged_once_more(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    org = build_org(proxy_app, db, "Alpha")
    _map(db, org.tenant_id)
    owner = org.people["owner"]
    many.plan = [many_proxy.ManyResponse(401, {}, b'{"detail":"Could not validate credentials"}')]
    assert _call(owner, "GET", _org(org.tenant_id, "whatsapp/accounts")).status_code == 200
    assert many.exchanges == 2
    many.plan = [many_proxy.ManyResponse(401, {}, b"{}"), many_proxy.ManyResponse(401, {}, b"{}")]
    response = _call(owner, "GET", _org(org.tenant_id, "whatsapp/accounts"))
    assert response.status_code == 502 and response.json()["error"]["code"] == "MANY_UNAVAILABLE"


def test_many_statuses_pass_through_and_transport_failures_become_502(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    org = build_org(proxy_app, db, "Alpha")
    _map(db, org.tenant_id)
    owner = org.people["owner"]
    many.plan = [
        many_proxy.ManyResponse(403, {"content-type": "application/json"}, b'{"detail":"no"}'),
        many_proxy.ManyResponse(404, {"content-type": "application/json"}, b'{"detail":"gone"}'),
        many_proxy.ManyResponse(429, {"retry-after": "7"}, b"slow down"),
        many_proxy.ManyUnavailable("transport error"),
    ]
    path = _org(org.tenant_id, "whatsapp/accounts")
    assert _call(owner, "GET", path).status_code == 403
    assert _call(owner, "GET", path).json() == {"detail": "gone"}
    slow = _call(owner, "GET", path)
    assert slow.status_code == 429 and slow.headers["retry-after"] == "7"
    down = _call(owner, "GET", path)
    assert down.status_code == 502 and down.json()["error"]["code"] == "MANY_UNAVAILABLE"
    assert "transport" not in down.text  # the cause stays in the server


def test_set_cookie_and_other_many_headers_are_not_relayed(
    proxy_app: FastAPI, db: Session, many: FakeMany
) -> None:
    org = build_org(proxy_app, db, "Alpha")
    _map(db, org.tenant_id)
    many.plan = [
        many_proxy.ManyResponse(
            200, {"content-type": "text/csv", "content-disposition": "attachment"}, b"a,b"
        )
    ]
    response = _call(org.people["owner"], "GET", _org(org.tenant_id, "whatsapp/contacts"))
    assert response.headers["content-type"].startswith("text/csv") and response.content == b"a,b"
    assert "set-cookie" not in response.headers


def test_startup_refuses_the_proxy_without_what_it_needs() -> None:
    with pytest.raises(RuntimeError, match="IDENTITY_V2_ENABLED and SSO_ISSUER_ENABLED"):
        validate_startup_settings(proxy_settings(identity_v2_enabled=False))
    with pytest.raises(RuntimeError, match="MANY_API_BASE_URL"):
        validate_startup_settings(proxy_settings(many_api_base_url=""))
    validate_startup_settings(proxy_settings())
