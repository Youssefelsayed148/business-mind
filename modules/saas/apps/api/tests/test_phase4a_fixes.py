"""Phase 4A: Phase 3 review items 3 and 7 (docs/PHASE-3-REVIEW.md, "Open before enabling any flag").

Item 3: a location-limited Admin must not change the organization's retention setting or create or
read change requests (organization-wide). Item 7: on the team route an Admin must not replace a
pending Owner (or Admin) invitation with a lower one. Synthetic data only.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Invitation
from tests.helpers import csrf_headers
from tests.identity_helpers import Person
from tests.test_phase3_review_fixes import _limit_to_a_new_location
from tests.test_team_management import invite, team_org, url


def _retention(person: Person, org: Any) -> Any:
    return person.client.patch(
        f"/api/v1/tenants/{org.tenant_id}",
        json={"retention_days": 30},
        headers=csrf_headers(person.client),
    )


def _list_requests(person: Person, org: Any) -> Any:
    return person.client.get(url(org, "/change-requests"))


def _create_request(person: Person, org: Any) -> Any:
    return person.client.post(
        url(org, "/change-requests"),
        data={"type": "other", "text": "Please change something."},
        headers=csrf_headers(person.client),
    )


ORGANIZATION_WIDE = {
    "retention": _retention,
    "list_change_requests": _list_requests,
    "create_change_request": _create_request,
}


@pytest.mark.parametrize("name", sorted(ORGANIZATION_WIDE))
def test_a_location_limited_admin_cannot_use_organization_wide_settings(
    v2_app: FastAPI, db: Session, name: str
) -> None:
    org = team_org(v2_app, db)
    admin = org.people["admin"]
    call = ORGANIZATION_WIDE[name]
    assert call(admin, org).status_code in (200, 201), "an unrestricted Admin keeps access"
    _limit_to_a_new_location(db, org.tenant_id, admin.user_id)
    refused = call(admin, org)
    assert refused.status_code == 403, refused.text
    assert call(org.people["owner"], org).status_code in (200, 201)


def _pending(db: Session, org: Any, email: str) -> list[Invitation]:
    db.expire_all()
    return list(
        db.scalars(
            select(Invitation).where(
                Invitation.tenant_id == org.tenant_id,
                Invitation.email == email,
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
            )
        )
    )


@pytest.mark.parametrize("pending_role", ["owner", "admin"])
def test_an_admin_cannot_replace_a_pending_privileged_invitation(
    v2_app: FastAPI, db: Session, pending_role: str
) -> None:
    org = team_org(v2_app, db)
    address = f"future-{pending_role}@example.com"
    assert invite(org.people["owner"], org, address, pending_role).status_code == 202
    before = _pending(db, org, address)
    assert len(before) == 1
    refused = invite(org.people["admin"], org, address, "viewer")
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["code"] == "OWNER_REQUIRED"
    after = _pending(db, org, address)
    assert [row.id for row in after] == [row.id for row in before]
    assert after[0].org_role == pending_role


def test_an_owner_can_still_replace_a_pending_invitation(v2_app: FastAPI, db: Session) -> None:
    org = team_org(v2_app, db)
    address = "replace-me@example.com"
    assert invite(org.people["owner"], org, address, "admin").status_code == 202
    assert invite(org.people["owner"], org, address, "viewer").status_code == 202
    pending = _pending(db, org, address)
    assert [row.org_role for row in pending] == ["viewer"]


def test_an_admin_can_still_replace_a_pending_lower_invitation(
    v2_app: FastAPI, db: Session
) -> None:
    org = team_org(v2_app, db)
    address = "lower@example.com"
    assert invite(org.people["admin"], org, address, "viewer").status_code == 202
    assert invite(org.people["admin"], org, address, "agent").status_code == 202
    assert [row.org_role for row in _pending(db, org, address)] == ["agent"]
