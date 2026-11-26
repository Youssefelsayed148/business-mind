"""Migrations 0032 to 0034: single head, up/down/up, backfill, legacy columns intact."""

from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Membership, Tenant, User
from tests.conftest import API_DIR, run_migrations

PREVIOUS_HEAD = "0031_contact_erasure"
NEW_TABLES = {
    "locations",
    "membership_locations",
    "agencies",
    "agency_memberships",
    "agency_grants",
    "agency_grant_assignees",
    "agency_grant_locations",
    "user_mfa",
    "user_recovery_codes",
    "password_reset_tokens",
}


def _tables(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _columns(engine: Engine, table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table)}


def _url(engine: Engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def _roles(conn: Connection, tenant_id: UUID) -> dict[str, str | None]:
    rows = conn.execute(
        text("SELECT role, org_role FROM memberships WHERE tenant_id = :t"), {"t": tenant_id}
    ).all()
    return {str(role): org_role for role, org_role in rows}


def _seed_memberships(db: Session) -> tuple[Tenant, dict[str, User]]:
    tenant = Tenant(id=uuid4(), name="Identity Org", slug=f"identity-{uuid4().hex[:10]}")
    db.add(tenant)
    users: dict[str, User] = {}
    for role in ("admin", "editor", "viewer"):
        user = User(id=uuid4(), email=f"{role}-{uuid4().hex[:8]}@example.test", password_hash="x")
        users[role] = user
        db.add(user)
    db.flush()
    for role, user in users.items():
        db.add(Membership(tenant_id=tenant.id, user_id=user.id, role=role))
    db.commit()
    return tenant, users


def test_single_head_chains_on_previous_head() -> None:
    config = Config(API_DIR / "alembic.ini")
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0034_roles_backfill"]
    chain = [rev.revision for rev in script.walk_revisions()][:4]
    assert chain == [
        "0034_roles_backfill",
        "0033_auth_security",
        "0032_identity_orgs",
        PREVIOUS_HEAD,
    ]


def test_up_down_up_with_backfill_keeps_legacy_columns(db: Session, engine: Engine) -> None:
    tenant, users = _seed_memberships(db)
    url = _url(engine)
    db.close()

    # Backfill ran on the freshly migrated head: legacy role stays, org_role is mapped.
    with engine.connect() as conn:
        rows = _roles(conn, tenant.id)
    # Rows inserted after the backfill have no org_role: the backfill is one-shot.
    assert rows == {"admin": None, "editor": None, "viewer": None}

    run_migrations(url, upgrade_to="", downgrade_to=PREVIOUS_HEAD)
    assert not (NEW_TABLES & _tables(engine))
    assert "org_role" not in _columns(engine, "memberships")
    assert "many_workspace_id" not in _columns(engine, "tenants")
    for table in ("channel_connections", "contacts", "sources"):
        assert "location_id" not in _columns(engine, table)
    # Legacy data survives the downgrade untouched.
    with engine.connect() as conn:
        legacy = {
            r[0]
            for r in conn.execute(
                text("SELECT role FROM memberships WHERE tenant_id = :t"), {"t": tenant.id}
            )
        }
    assert legacy == {"admin", "editor", "viewer"}

    run_migrations(url)  # up again: the backfill now maps existing rows
    assert NEW_TABLES <= _tables(engine)
    with engine.connect() as conn:
        mapped = _roles(conn, tenant.id)
    assert mapped == {"admin": "admin", "editor": "agent", "viewer": "viewer"}
    # Nobody was promoted to owner or manager by the backfill.
    with engine.connect() as conn:
        promoted = conn.execute(
            text("SELECT count(*) FROM memberships WHERE org_role IN ('owner','manager')")
        ).scalar_one()
    assert promoted == 0


def test_backfill_downgrade_clears_only_mapped_values(db: Session, engine: Engine) -> None:
    tenant, users = _seed_memberships(db)
    url = _url(engine)
    # An explicit later assignment (manager) must survive a 0034 downgrade.
    db.execute(
        text("UPDATE memberships SET org_role = 'manager' WHERE tenant_id=:t AND role='editor'"),
        {"t": tenant.id},
    )
    db.execute(
        text("UPDATE memberships SET org_role = 'agent' WHERE tenant_id=:t AND role='viewer'"),
        {"t": tenant.id},
    )
    db.execute(
        text("UPDATE memberships SET org_role = 'admin' WHERE tenant_id=:t AND role='admin'"),
        {"t": tenant.id},
    )
    db.commit()
    db.close()

    run_migrations(url, upgrade_to="", downgrade_to="0033_auth_security")
    with engine.connect() as conn:
        after = _roles(conn, tenant.id)
    assert after == {"admin": None, "editor": "manager", "viewer": "agent"}
    run_migrations(url)


def test_constraints_reject_bad_values(db: Session, engine: Engine) -> None:
    tenant, users = _seed_memberships(db)
    other = Tenant(id=uuid4(), name="Other", slug=f"other-{uuid4().hex[:10]}")
    db.add(other)
    db.commit()

    for statement in (
        "UPDATE memberships SET org_role='superuser'",
        "UPDATE memberships SET location_scope='some'",
        "INSERT INTO locations (id, tenant_id, name, status, created_at) "
        f"VALUES (gen_random_uuid(), '{tenant.id}', '  ', 'active', now())",
        "INSERT INTO agencies (id, name, status, created_at) "
        "VALUES (gen_random_uuid(), 'A', 'gone', now())",
    ):
        with pytest.raises(IntegrityError):
            db.execute(text(statement))
        db.rollback()

    # An agency grant can never carry Owner as its cap.
    db.execute(
        text("INSERT INTO agencies (id, name, created_at) VALUES (:a, 'Agency', now())"),
        {"a": (agency := uuid4())},
    )
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO agency_grants (id, agency_id, tenant_id, role_cap, granted_at) "
                "VALUES (gen_random_uuid(), :a, :t, 'owner', now())"
            ),
            {"a": agency, "t": tenant.id},
        )
    db.rollback()


def test_location_foreign_keys_are_tenant_scoped(db: Session, engine: Engine) -> None:
    tenant_a, _ = _seed_memberships(db)
    tenant_b = Tenant(id=uuid4(), name="B", slug=f"b-{uuid4().hex[:10]}")
    db.add(tenant_b)
    db.commit()
    location_b = uuid4()
    db.execute(
        text(
            "INSERT INTO locations (id, tenant_id, name, created_at) "
            "VALUES (:i, :t, 'Branch', now())"
        ),
        {"i": location_b, "t": tenant_b.id},
    )
    db.commit()
    # A contact of tenant A cannot point at tenant B's location.
    with pytest.raises(IntegrityError):
        db.execute(
            text(
                "INSERT INTO contacts (id, tenant_id, display_name, source_channel, stage, "
                "tags, custom_fields, consent, created_at, updated_at, location_id) "
                "VALUES (gen_random_uuid(), :t, 'x', 'website', 'new', '[]', '{}', '{}', "
                "now(), now(), :l)"
            ),
            {"t": tenant_a.id, "l": location_b},
        )
    db.rollback()
