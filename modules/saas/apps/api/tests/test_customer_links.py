# ruff: noqa: F811
"""Phase 5A: the customer link (docs/DATA-UNIFICATION.md). A fake Many answers; synthetic data.

Covers: flag off, staff only, the link rules (linked, many_only, saas_only, conflict), no
duplicates and idempotent re-runs, dry run, channels the organization does not own, Instagram
claims, tenant isolation, erased links stay erased, Many failures, and that no raw external id is
stored. The migration test checks up, down and up again.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ChannelConnection, Contact, ContactIdentity, CustomerLink
from app.identity import many_proxy
from app.linking.service import _Derived, _state, link_digest
from tests.conftest import run_migrations
from tests.helpers import make_bot, seeded_tenant
from tests.test_many_proxy import (  # noqa: F401  (fixtures)
    FakeMany,
    _map,
    many,
    proxy_settings,
)

JSON_HEADERS = {"content-type": "application/json"}


def _ok(payload: Any) -> many_proxy.ManyResponse:
    return many_proxy.ManyResponse(200, JSON_HEADERS, json.dumps(payload).encode())


@pytest.fixture
def uni_app(v2_app: FastAPI) -> FastAPI:
    v2_app.dependency_overrides[get_settings] = lambda: proxy_settings(
        data_unification_enabled=True
    )
    return v2_app


def _lead(platform: str, channel: str, external: str, lead_id: str | None = None) -> dict[str, Any]:
    field = {
        "instagram": "instagram_account_id",
        "whatsapp": "whatsapp_account_id",
        "facebook": "facebook_page_id",
    }[platform]
    return {
        "id": lead_id or str(uuid4()),
        "platform": platform,
        "ig_user_id": external,
        field: channel,
    }


def _connection(
    db: Session, users: Any, channel: str, ref: str, bot_id: UUID | None = None
) -> ChannelConnection:
    bot_id = bot_id or UUID(make_bot(users)["id"])
    connection = ChannelConnection(
        tenant_id=users.tenant_id,
        bot_id=bot_id,
        channel=channel,
        display_name=f"{channel} {ref[:4]}",
        many_base_url="https://many.example.test",
        many_channel_ref=ref,
        status="active",
        secret_ciphertext="not-a-real-secret",
        secret_key_version=1,
        health_status="unknown",
    )
    db.add(connection)
    db.flush()
    return connection


def _identity(
    db: Session, users: Any, connection: ChannelConnection, channel: str, external: str
) -> Contact:
    contact = Contact(tenant_id=users.tenant_id, display_name="Synthetic", source_channel=channel)
    db.add(contact)
    db.flush()
    db.add(
        ContactIdentity(
            tenant_id=users.tenant_id,
            contact_id=contact.id,
            channel=channel,
            external_id=external,
            connection_id=connection.id,
        )
    )
    db.flush()
    return contact


def _sync(
    users: Any,
    many: FakeMany,
    wa: list[str],
    fb: list[str],
    leads: list[dict[str, Any]],
    *,
    dry: bool = False,
) -> Any:
    many.plan.extend([_ok([{"id": i} for i in wa]), _ok([{"id": i} for i in fb]), _ok(leads)])
    suffix = "?dry_run=true" if dry else ""
    return users.call(
        "staff", "POST", f"/api/v1/platform/tenants/{users.tenant_id}/customer-links/sync{suffix}"
    )


def _links(db: Session, tenant_id: UUID) -> list[CustomerLink]:
    return list(db.scalars(select(CustomerLink).where(CustomerLink.tenant_id == tenant_id)))


def _world(uni_app: FastAPI, db: Session, label: str) -> tuple[Any, str, str, str]:
    users = seeded_tenant(uni_app, db, prefix=label)
    _map(db, users.tenant_id)
    w1, w2, f1 = str(uuid4()), str(uuid4()), str(uuid4())
    return users, w1, w2, f1


# --- flag, roles -----------------------------------------------------------------------------


def test_flag_off_answers_like_an_unknown_route(
    v2_app: FastAPI, db: Session, many: FakeMany
) -> None:
    v2_app.dependency_overrides[get_settings] = lambda: proxy_settings()
    users = seeded_tenant(v2_app, db, prefix="cl-off")
    base = f"/api/v1/platform/tenants/{users.tenant_id}"
    for method, path in (
        ("POST", f"{base}/customer-links/sync"),
        ("GET", f"{base}/customer-links"),
        ("GET", f"{base}/many-channel-claims"),
        ("POST", f"{base}/many-channel-claims"),
    ):
        assert users.call("staff", method, path).status_code == 404, path
    assert many.calls == []


def test_only_platform_staff_may_use_the_routes(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, *_ = _world(uni_app, db, "cl-roles")
    base = f"/api/v1/platform/tenants/{users.tenant_id}"
    for role in ("admin", "editor", "viewer"):
        for method, path in (
            ("POST", f"{base}/customer-links/sync"),
            ("GET", f"{base}/customer-links"),
        ):
            assert users.call(role, method, path).status_code == 403, (role, path)
    assert many.calls == []


# --- the link rules ---------------------------------------------------------------------------


def test_the_rules_link_many_only_saas_only_and_ignore_other_channels(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, w1, w2, f1 = _world(uni_app, db, "cl-rules")
    connection = _connection(db, users, "whatsapp", w1)
    both = _identity(db, users, connection, "whatsapp", "u1")  # also a Many lead -> linked
    only_saas = _identity(db, users, connection, "whatsapp", "u3")  # no lead -> saas_only
    db.commit()
    leads = [
        _lead("whatsapp", w1, "u1"),
        _lead("whatsapp", w2, "u2"),  # many_only
        _lead("facebook", f1, "p1"),  # many_only
        _lead("instagram", str(uuid4()), "ig1"),  # Instagram account nobody claimed: ignored
        _lead("whatsapp", str(uuid4()), "u9"),  # another workspace's number: ignored
    ]
    response = _sync(users, many, [w1, w2], [f1], leads)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["created"] == 4 and body["ignored_leads"] == 2
    assert body["by_state"] == {"linked": 1, "many_only": 2, "saas_only": 1}

    by = {(r.platform, r.state): r for r in _links(db, users.tenant_id)}
    assert by[("whatsapp", "linked")].contact_id == both.id
    assert by[("whatsapp", "saas_only")].contact_id == only_saas.id
    assert by[("whatsapp", "many_only")].contact_id is None


def test_a_second_run_changes_nothing_and_makes_no_duplicates(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, w1, w2, f1 = _world(uni_app, db, "cl-idem")
    connection = _connection(db, users, "whatsapp", w1)
    _identity(db, users, connection, "whatsapp", "u1")
    db.commit()
    leads = [_lead("whatsapp", w1, "u1"), _lead("whatsapp", w1, "u1"), _lead("whatsapp", w2, "u2")]
    first = _sync(users, many, [w1, w2], [], leads).json()
    assert first["created"] == 2  # the repeated lead collapses onto one identity
    before = {(r.id, r.updated_at) for r in _links(db, users.tenant_id)}
    second = _sync(users, many, [w1, w2], [], leads).json()
    assert second["created"] == 0 and second["updated"] == 0 and second["unchanged"] == 2
    db.expire_all()
    assert {(r.id, r.updated_at) for r in _links(db, users.tenant_id)} == before


def test_a_dry_run_writes_nothing(uni_app: FastAPI, db: Session, many: FakeMany) -> None:
    users, w1, _w2, _f1 = _world(uni_app, db, "cl-dry")
    response = _sync(users, many, [w1], [], [_lead("whatsapp", w1, "u1")], dry=True)
    assert response.json()["created"] == 1 and response.json()["dry_run"] is True
    assert _links(db, users.tenant_id) == []


def test_an_identity_with_two_contacts_is_a_conflict_and_is_not_resolved() -> None:
    first, second = uuid4(), uuid4()
    assert _state(_Derived(contact_ids={first, second}, many_lead_id="l1")) == ("conflict", None)
    assert _state(_Derived(contact_ids={first}, many_lead_id="l1")) == ("linked", first)
    assert _state(_Derived(contact_ids={first})) == ("saas_only", first)
    assert _state(_Derived(many_lead_id="l1")) == ("many_only", None)


def test_the_digest_is_scoped_and_hides_the_raw_id() -> None:
    t1, t2 = uuid4(), uuid4()
    a = link_digest(t1, "whatsapp", "c1", "+201001234567")
    assert len(a) == 64 and "201001234567" not in a
    assert a != link_digest(t2, "whatsapp", "c1", "+201001234567")  # other tenant
    assert a != link_digest(t1, "whatsapp", "c2", "+201001234567")  # other channel
    assert a != link_digest(t1, "facebook", "c1", "+201001234567")  # other platform


def test_the_raw_identity_lives_only_in_its_own_column_until_erased(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, w1, *_ = _world(uni_app, db, "cl-raw")
    _sync(users, many, [w1], [], [_lead("whatsapp", w1, "SECRET-EXTERNAL-ID-123")])
    (row,) = _links(db, users.tenant_id)
    assert row.external_id == "SECRET-EXTERNAL-ID-123"  # kept so Many can be asked to erase
    assert row.external_id not in row.external_id_digest
    for line in db.execute(text("SELECT * FROM customer_links")).all():
        others = [str(v) for k, v in line._mapping.items() if k != "external_id"]
        assert "SECRET-EXTERNAL-ID-123" not in " ".join(others)


# --- volume (stand-in for a restored copy; the owner runs the real one) ------------------------


def test_a_large_repeated_dataset_has_no_duplicates_and_reruns_cleanly(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, w1, w2, f1 = _world(uni_app, db, "cl-volume")
    connection = _connection(db, users, "whatsapp", w1)
    for n in range(300):  # chat contacts that Many also knows
        _identity(db, users, connection, "whatsapp", f"person-{n}")
    db.commit()
    unique = 2000
    leads = [
        _lead("whatsapp", w1 if n < 1000 else w2, f"person-{n}")
        for _ in range(3)  # every person repeated three times, as a messy copy can be
        for n in range(unique)
    ]
    first = _sync(users, many, [w1, w2], [f1], leads).json()
    assert first["created"] == unique and first["ignored_leads"] == 0
    assert first["by_state"] == {"linked": 300, "many_only": unique - 300}
    rows = _links(db, users.tenant_id)
    assert len(rows) == unique
    assert len({(r.platform, r.many_channel_id, r.external_id_digest) for r in rows}) == unique
    second = _sync(users, many, [w1, w2], [f1], leads).json()
    assert second["created"] == 0 and second["updated"] == 0 and second["unchanged"] == unique
    assert len(_links(db, users.tenant_id)) == unique


# --- Instagram claims -------------------------------------------------------------------------


def test_instagram_leads_count_only_after_staff_claim_the_account(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, *_ = _world(uni_app, db, "cl-ig")
    account = str(uuid4())
    lead = _lead("instagram", account, "ig-user-1")
    assert _sync(users, many, [], [], [lead]).json()["ignored_leads"] == 1
    base = f"/api/v1/platform/tenants/{users.tenant_id}/many-channel-claims"
    claimed = users.call(
        "staff", "POST", base, json={"platform": "instagram", "many_channel_id": account}
    )
    assert claimed.status_code == 201
    body = _sync(users, many, [], [], [lead]).json()
    assert body["created"] == 1 and body["by_state"] == {"many_only": 1}
    assert users.call("staff", "GET", base).json() == [
        {"platform": "instagram", "many_channel_id": account}
    ]
    assert users.call("staff", "DELETE", f"{base}/instagram/{account}").status_code == 204


def test_a_channel_cannot_belong_to_two_organizations(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    a, *_ = _world(uni_app, db, "cl-own-a")
    b, *_ = _world(uni_app, db, "cl-own-b")
    account = str(uuid4())
    body = {"platform": "instagram", "many_channel_id": account}
    assert (
        a.call(
            "staff",
            "POST",
            f"/api/v1/platform/tenants/{a.tenant_id}/many-channel-claims",
            json=body,
        ).status_code
        == 201
    )
    taken = b.call(
        "staff", "POST", f"/api/v1/platform/tenants/{b.tenant_id}/many-channel-claims", json=body
    )
    assert taken.status_code == 409 and taken.json()["error"]["code"] == "CHANNEL_ALREADY_CLAIMED"


# --- isolation, erased, failures --------------------------------------------------------------


def test_organizations_never_see_each_others_links(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    a, w1, _w2, _f1 = _world(uni_app, db, "cl-iso-a")
    b, *_ = _world(uni_app, db, "cl-iso-b")
    lead = _lead("whatsapp", w1, "same-person")
    _sync(a, many, [w1], [], [lead])
    # B's workspace does not own W1, so the same lead is ignored for B.
    body = _sync(b, many, [str(uuid4())], [], [lead]).json()
    assert body["created"] == 0 and body["ignored_leads"] == 1
    assert len(_links(db, a.tenant_id)) == 1 and _links(db, b.tenant_id) == []
    listed = b.call("staff", "GET", f"/api/v1/platform/tenants/{b.tenant_id}/customer-links").json()
    assert listed == {"total": 0, "items": []}


def test_an_erased_link_is_never_linked_again(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, w1, *_ = _world(uni_app, db, "cl-erased")
    lead = _lead("whatsapp", w1, "u1")
    _sync(users, many, [w1], [], [lead])
    row = _links(db, users.tenant_id)[0]
    row.state, row.many_lead_id = "erased", None
    db.commit()
    body = _sync(users, many, [w1], [], [lead]).json()
    assert body["skipped_erased"] == 1 and body["created"] == 0
    db.expire_all()
    assert _links(db, users.tenant_id)[0].state == "erased"


def test_many_failing_writes_nothing_and_answers_502(
    uni_app: FastAPI, db: Session, many: FakeMany
) -> None:
    users, w1, *_ = _world(uni_app, db, "cl-down")
    many.plan.append(many_proxy.ManyUnavailable("down"))
    response = users.call(
        "staff", "POST", f"/api/v1/platform/tenants/{users.tenant_id}/customer-links/sync"
    )
    assert response.status_code == 502 and response.json()["error"]["code"] == "MANY_UNAVAILABLE"
    assert _links(db, users.tenant_id) == []


def test_an_unusable_lead_list_is_refused(uni_app: FastAPI, db: Session, many: FakeMany) -> None:
    users, w1, *_ = _world(uni_app, db, "cl-bad")
    many.plan.extend([_ok([]), _ok([]), _ok({"not": "a list"})])
    response = users.call(
        "staff", "POST", f"/api/v1/platform/tenants/{users.tenant_id}/customer-links/sync"
    )
    assert response.status_code == 502


# --- migration --------------------------------------------------------------------------------


def test_migration_0036_goes_up_down_and_up(db: Session, engine: Engine) -> None:
    url = engine.url.render_as_string(hide_password=False)
    db.close()
    new = {"customer_links", "many_channel_claims"}
    assert new <= set(inspect(engine).get_table_names())
    run_migrations(url, upgrade_to="", downgrade_to="0035_invitation_locations")
    assert not (new & set(inspect(engine).get_table_names()))
    run_migrations(url)
    assert new <= set(inspect(engine).get_table_names())
