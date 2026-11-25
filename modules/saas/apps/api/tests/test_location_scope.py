"""Location scope (design 4.2): fail closed, tenant-scoped, org-wide rows hidden from limited."""

from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Contact, Location, MembershipLocation
from app.identity.access import resolve_access
from app.identity.locations import (
    location_allowed,
    location_filter,
    member_location_ids,
    narrower,
    validate_locations_in_tenant,
)
from tests.identity_helpers import join, make_person, make_tenant


def _contact(
    db: Session, tenant_id: UUID, location_id: UUID | None = None, name: str = "c"
) -> Contact:
    contact = Contact(
        id=uuid4(),
        tenant_id=tenant_id,
        display_name=name,
        source_channel="website",
        location_id=location_id,
    )
    db.add(contact)
    db.flush()
    return contact


def test_pure_scope_rules_fail_closed() -> None:
    a, b = uuid4(), uuid4()
    assert location_allowed(None, None) and location_allowed(None, a)
    assert location_allowed(frozenset({a}), a)
    assert not location_allowed(frozenset({a}), b)
    assert not location_allowed(frozenset({a}), None)  # org-wide hidden from limited
    assert not location_allowed(frozenset(), a) and not location_allowed(frozenset(), None)
    assert narrower(None, None) is None
    assert narrower(None, frozenset({a})) == frozenset({a})
    assert narrower(frozenset({a, b}), frozenset({b})) == frozenset({b})
    assert narrower(frozenset({a}), frozenset({b})) == frozenset()


def test_filter_restricts_a_real_query(db: Session) -> None:
    tenant_id = make_tenant(db)
    north = Location(id=uuid4(), tenant_id=tenant_id, name="North")
    south = Location(id=uuid4(), tenant_id=tenant_id, name="South")
    db.add_all([north, south])
    db.flush()
    names = {
        "n": _contact(db, tenant_id, north.id, "n"),
        "s": _contact(db, tenant_id, south.id, "s"),
        "org": _contact(db, tenant_id, None, "org"),
    }
    db.commit()

    def visible(scope: frozenset[UUID] | None) -> set[str]:
        rows = db.execute(
            select(Contact.display_name).where(
                Contact.tenant_id == tenant_id, location_filter(Contact.location_id, scope)
            )
        ).scalars()
        return set(rows)

    assert visible(None) == {"n", "s", "org"}
    assert visible(frozenset({north.id})) == {"n"}
    assert visible(frozenset({north.id, south.id})) == {"n", "s"}
    assert visible(frozenset()) == set()  # a limited member with no locations sees nothing
    assert names


def test_membership_locations_and_validation_are_tenant_scoped(db: Session, app: FastAPI) -> None:
    tenant_id, other = make_tenant(db, "Mine"), make_tenant(db, "Other")
    person = make_person(app, "limited", db=db)
    join(db, tenant_id, person.user_id, "agent", location_scope="limited")
    mine = Location(id=uuid4(), tenant_id=tenant_id, name="Here")
    theirs = Location(id=uuid4(), tenant_id=other, name="There")
    archived = Location(id=uuid4(), tenant_id=tenant_id, name="Old", status="archived")
    db.add_all([mine, theirs, archived])
    db.commit()
    db.add(MembershipLocation(tenant_id=tenant_id, user_id=person.user_id, location_id=mine.id))
    db.commit()
    assert member_location_ids(db, tenant_id, person.user_id) == frozenset({mine.id})
    with pytest.raises(IntegrityError):  # another tenant's location cannot be attached
        db.execute(
            insert(MembershipLocation).values(
                tenant_id=tenant_id, user_id=person.user_id, location_id=theirs.id
            )
        )
    db.rollback()
    assert validate_locations_in_tenant(db, tenant_id, [mine.id]) == frozenset({mine.id})
    for bad in ([theirs.id], [archived.id], [uuid4()], [mine.id, theirs.id]):
        with pytest.raises(ValueError):
            validate_locations_in_tenant(db, tenant_id, bad)


def test_resolve_access_reports_the_members_scope(db: Session, app: FastAPI) -> None:
    from app.db.models import Membership, Tenant, User

    tenant_id = make_tenant(db)
    full = make_person(app, "full", db=db)
    limited = make_person(app, "limited", db=db)
    join(db, tenant_id, full.user_id, "agent")
    join(db, tenant_id, limited.user_id, "agent", location_scope="limited")
    here = Location(id=uuid4(), tenant_id=tenant_id, name="Here")
    db.add(here)
    db.commit()
    db.add(MembershipLocation(tenant_id=tenant_id, user_id=limited.user_id, location_id=here.id))
    db.commit()
    tenant = db.get(Tenant, tenant_id)
    for person, expected in ((full, None), (limited, frozenset({here.id}))):
        access = resolve_access(
            db,
            user=db.get(User, person.user_id),  # type: ignore[arg-type]
            tenant=tenant,  # type: ignore[arg-type]
            membership=db.get(Membership, (tenant_id, person.user_id)),
        )
        assert access is not None and access.location_ids == expected


def test_limited_members_are_refused_everywhere_until_filters_are_wired(
    v2_app: FastAPI, db: Session
) -> None:
    """Fail closed: with the flag on a location-limited caller gets no tenant route yet."""
    tenant_id = make_tenant(db)
    limited = make_person(v2_app, "limited", db=db)
    join(db, tenant_id, limited.user_id, "agent", location_scope="limited")
    full = make_person(v2_app, "full", db=db)
    join(db, tenant_id, full.user_id, "agent")
    for path in ("/inbox", "/contacts", "/analytics"):
        refused = limited.client.get(f"/api/v1/tenants/{tenant_id}{path}")
        assert refused.status_code == 403, path
        assert "LOCATION_SCOPE_UNSUPPORTED" in refused.text
        assert full.client.get(f"/api/v1/tenants/{tenant_id}{path}").status_code == 200, path


def test_flag_off_ignores_location_scope_entirely(app: FastAPI, db: Session) -> None:
    tenant_id = make_tenant(db)
    limited = make_person(app, "limited", db=db)
    join(db, tenant_id, limited.user_id, "agent", location_scope="limited")
    assert limited.client.get(f"/api/v1/tenants/{tenant_id}/contacts").status_code == 200
