"""Fixtures for the Phase 3 identity tests (synthetic data only)."""

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session as OrmSession

from app.db.models import Membership, Tenant, User
from tests.helpers import PASSWORD

# Stored legacy role that corresponds to each organization role. Only the legacy
# column matters while the identity flag is off (viewer, editor, admin).
LEGACY_FOR = {
    "owner": "admin",
    "admin": "admin",
    "manager": "editor",
    "agent": "editor",
    "viewer": "viewer",
}
ROLES = ("owner", "admin", "manager", "agent", "viewer")


@dataclass
class Person:
    client: TestClient
    user_id: UUID
    email: str


@dataclass
class Org:
    tenant_id: UUID
    people: dict[str, Person] = field(default_factory=dict)


def make_person(app: FastAPI, label: str, *, staff: bool = False, db: OrmSession) -> Person:
    email = f"{label}-{uuid4().hex[:10]}@example.com"
    # Handlers may fail on synthetic ids; the matrix reads the status code only.
    client = TestClient(app, raise_server_exceptions=False)
    response = client.post("/api/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    user_id = UUID(response.json()["id"])
    if staff:
        db.execute(update(User).where(User.id == user_id).values(is_platform_staff=True))
        db.commit()
    return Person(client=client, user_id=user_id, email=email)


def make_tenant(db: OrmSession, name: str = "Org") -> UUID:
    tenant = Tenant(id=uuid4(), name=name, slug=f"{name.lower()}-{uuid4().hex[:10]}")
    db.add(tenant)
    db.commit()
    return tenant.id


def join(
    db: OrmSession,
    tenant_id: UUID,
    user_id: UUID,
    role: str,
    *,
    location_scope: str = "all",
    org_role: str | None | bool = True,
) -> None:
    """Add a membership. `org_role=True` stores the new role, None leaves it unset."""
    value = role if org_role is True else (None if org_role is None else str(org_role))
    db.add(
        Membership(
            tenant_id=tenant_id,
            user_id=user_id,
            role=LEGACY_FOR[role],
            org_role=value,
        )
    )
    db.flush()
    if location_scope != "all":
        db.execute(
            update(Membership)
            .where(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
            .values(location_scope=location_scope)
        )
    db.commit()


def build_org(app: FastAPI, db: OrmSession, name: str = "Org") -> Org:
    org = Org(tenant_id=make_tenant(db, name))
    for role in ROLES:
        person = make_person(app, f"{name.lower()}-{role}", db=db)
        join(db, org.tenant_id, person.user_id, role)
        org.people[role] = person
    return org
