# ruff: noqa: F811
"""Phase 5B: what a client Owner or Admin sees of the customer link. A fake Many fills the table
through the staff sync; the client routes read only the SaaS table. Synthetic data only.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy.orm import Session

from app.core.config import get_settings
from tests.helpers import seeded_tenant
from tests.identity_helpers import build_org
from tests.test_customer_links import (  # type: ignore[attr-defined]  # noqa: F401
    FakeMany,
    _connection,
    _identity,
    _lead,
    _links,
    _map,
    _sync,
    _world,
    many,
    proxy_settings,
    uni_app,
)
from tests.test_phase3_review_fixes import _limit_to_a_new_location


def _lead_named(platform: str, channel: str, external: str, name: str, when: str) -> dict[str, Any]:
    lead = _lead(platform, channel, external)
    lead["username"] = name
    lead["captured_at"] = when
    return lead


def _filled(uni_app: FastAPI, db: Session, many: FakeMany, label: str):  # type: ignore[no-untyped-def]
    users, w1, w2, f1 = _world(uni_app, db, label)
    connection = _connection(db, users, "whatsapp", w1)
    contact = _identity(db, users, connection, "whatsapp", "u1")
    db.commit()
    leads = [
        _lead_named("whatsapp", w1, "u1", "dana_wa", "2026-05-01T10:00:00+00:00"),
        _lead_named("whatsapp", w2, "u2", "عميل جديد", "2026-05-02T10:00:00+00:00"),
        _lead_named("facebook", f1, "p1", "omar.fb", "2026-05-03T10:00:00+00:00"),
    ]
    assert _sync(users, many, [w1, w2], [f1], leads).status_code == 200
    return users, contact


def _list(users: Any, role: str, query: str = "") -> Any:
    return users.call(
        "admin" if role == "owner" else role,
        "GET",
        f"/api/v1/tenants/{users.tenant_id}/customer-links{query}",
    )


def test_flag_off_answers_like_an_unknown_route(
    v2_app: FastAPI, db: Session, many: FakeMany
) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: proxy_settings()
    users = seeded_tenant(v2_app, db, prefix="clc-off")
    base = f"/api/v1/tenants/{users.tenant_id}"
    assert users.call("admin", "GET", f"{base}/customer-links").status_code == 404
    assert (
        users.call("admin", "GET", f"{base}/contacts/{uuid4()}/customer-links").status_code == 404
    )


def test_admin_sees_all_three_kinds_of_people_and_other_roles_are_refused(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, contact = _filled(uni_app, db, many, "clc-roles")
    body = users.call("admin", "GET", f"/api/v1/tenants/{users.tenant_id}/customer-links").json()
    assert body["total"] == 3
    by_name = {i["display_name"]: i for i in body["items"]}
    assert by_name["dana_wa"]["state"] == "linked"
    assert by_name["dana_wa"]["contact_id"] == str(contact.id)
    assert by_name["dana_wa"]["contact_name"] == "Synthetic"
    assert by_name["عميل جديد"]["state"] == "many_only"
    assert by_name["omar.fb"]["platform"] == "facebook"
    for role in ("editor", "viewer"):
        assert _list(users, role).status_code == 403, role
    # No raw external id travels to the browser.
    assert "u1" not in str(body) and "p1" not in str(body)


def test_filters_search_and_paging(uni_app: FastAPI, db: Session, many: FakeMany) -> None:
    users, _ = _filled(uni_app, db, many, "clc-filter")
    assert _list(users, "admin", "?platform=facebook").json()["total"] == 1
    assert _list(users, "admin", "?state=many_only").json()["total"] == 2
    assert _list(users, "admin", "?q=dana").json()["total"] == 1
    assert _list(users, "admin", "?q=Synthetic").json()["total"] == 1  # the linked contact's name
    assert _list(users, "admin", "?q=%25").json()["total"] == 0  # a wildcard is not a wildcard
    page = _list(users, "admin", "?limit=2&offset=2").json()
    assert page["total"] == 3 and len(page["items"]) == 1
    assert _list(users, "admin", "?platform=telegram").status_code == 422


def test_an_organization_never_sees_another_organizations_people(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    a, contact = _filled(uni_app, db, many, "clc-iso-a")
    b, *_ = _world(uni_app, db, "clc-iso-b")
    assert _list(b, "admin").json() == {"total": 0, "items": []}
    other = b.call(
        "admin", "GET", f"/api/v1/tenants/{b.tenant_id}/contacts/{contact.id}/customer-links"
    )
    assert other.status_code == 404
    mine = a.call(
        "admin", "GET", f"/api/v1/tenants/{a.tenant_id}/contacts/{contact.id}/customer-links"
    )
    assert [i["platform"] for i in mine.json()["items"]] == ["whatsapp"]


def test_erased_people_are_hidden(uni_app: FastAPI, db: Session, many: FakeMany) -> None:
    users, _ = _filled(uni_app, db, many, "clc-erased")
    row = next(r for r in _links(db, users.tenant_id) if r.display_name == "omar.fb")
    row.state, row.display_name = "erased", None
    db.commit()
    names = {i["display_name"] for i in _list(users, "admin").json()["items"]}
    assert names == {"dana_wa", "عميل جديد"}


def test_a_location_limited_admin_is_refused(uni_app: FastAPI, db: Session, many: FakeMany) -> None:
    org = build_org(uni_app, db, "ClcLoc")
    admin = org.people["admin"]
    _limit_to_a_new_location(db, org.tenant_id, admin.user_id)
    response = admin.client.get(f"/api/v1/tenants/{org.tenant_id}/customer-links")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "LOCATION_SCOPE_UNSUPPORTED"


def test_a_sync_updates_a_changed_username_and_not_an_unchanged_one(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, w1, w2, f1 = _world(uni_app, db, "clc-rename")
    first = [_lead_named("whatsapp", w1, "u1", "old_name", "2026-05-01T10:00:00+00:00")]
    _sync(users, many, [w1], [], first)
    assert _sync(users, many, [w1], [], first).json()["unchanged"] == 1
    renamed = [_lead_named("whatsapp", w1, "u1", "new_name", "2026-05-01T10:00:00+00:00")]
    assert _sync(users, many, [w1], [], renamed).json()["updated"] == 1
    assert _list(users, "admin").json()["items"][0]["display_name"] == "new_name"
