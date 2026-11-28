"""Phase 6G: Phase 3 review items 2 and 6 (docs/PHASE-3-REVIEW.md). Synthetic data only.

Item 2: a location-limited agency grant whose locations are all deleted must deny, never widen.
Item 6: with identity v2 on, the older invitation route answers the same for known and unknown
addresses.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import Invitation, Location, Tenant
from app.identity import agency as svc
from app.identity.access import resolve_access
from tests.helpers import csrf_headers
from tests.identity_helpers import make_person
from tests.test_agency_grants import _setup, _user
from tests.test_team_management import team_org, url


def test_a_limited_grant_with_all_locations_deleted_denies(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    place = Location(id=uuid4(), tenant_id=s.tenant_id, name="Only here")
    db.add(place)
    db.commit()
    grant = s.grant("manager", location_ids=[place.id])
    user, tenant = _user(db, s.agent), db.get(Tenant, s.tenant_id)
    assert tenant is not None
    before = resolve_access(db, user=user, tenant=tenant, membership=None)
    assert before is not None and before.location_ids == frozenset({place.id})
    # Deleting the location cascades to the grant's location rows (nothing else changes).
    db.execute(text("DELETE FROM locations WHERE id = :i"), {"i": place.id})
    db.commit()
    found = svc.active_grant_for(db, user_id=s.agent.user_id, tenant_id=s.tenant_id)
    assert found is not None and found.grant_id == grant.id
    assert found.location_ids == frozenset(), "an empty limited scope must match nothing"
    after = resolve_access(db, user=user, tenant=tenant, membership=None)
    assert after is not None and after.location_ids == frozenset()  # never None (unrestricted)


def test_an_unrestricted_grant_stays_unrestricted(v2_app: FastAPI, db: Session) -> None:
    s = _setup(v2_app, db)
    s.grant("manager")
    found = svc.active_grant_for(db, user_id=s.agent.user_id, tenant_id=s.tenant_id)
    assert found is not None and found.location_ids is None


def test_older_invitation_route_gives_one_answer_for_known_and_unknown_addresses(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    admin = org.people["admin"]
    stranger_email = f"nobody-{uuid4().hex[:8]}@example.com"  # no account
    outsider = make_person(v2_app, "outsider", db=db)  # an account that is not a member
    responses = [
        admin.client.post(
            url(org, "/invitations"),
            json={"email": email, "role": "viewer"},
            headers=csrf_headers(admin.client),
        )
        for email in (stranger_email, outsider.email)
    ]
    assert [r.status_code for r in responses] == [201, 201], [r.text for r in responses]
    assert all("USER_NOT_FOUND" not in r.text for r in responses)
    assert set(responses[0].json()) == set(responses[1].json())
    assert all(r.json()["link_path"].startswith("/accept-invite?token=") for r in responses)
    rows = {
        row.email: row.new_account
        for row in db.scalars(select(Invitation).where(Invitation.tenant_id == org.tenant_id))
    }
    assert rows[stranger_email] is True and rows[outsider.email] is False
