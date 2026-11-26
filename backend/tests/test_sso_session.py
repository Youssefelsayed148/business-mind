"""Shadow user and membership sync. Synthetic data only."""
import uuid

import pytest

from app.core.security import verify_password
from app.models.user import User
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.models.workspace import Workspace
from app.services.sso_assertion import Assertion, SSOAssertionError
from app.services.sso_session import ORG_TO_WORKSPACE_ROLE, sync_shadow_user


def workspace(db, org=None):
    ws = Workspace(name="Synthetic", slug=uuid.uuid4().hex, saas_tenant_id=org or uuid.uuid4())
    db.add(ws)
    db.flush()
    return ws


def client_assertion(ws, role="admin", sub=None, email="Person@Example.test"):
    return Assertion(
        sub=sub or uuid.uuid4(), jti=uuid.uuid4().hex, scope="client", email=email.lower(), mfa=True,
        org=ws.saas_tenant_id, workspace=ws.id, role=role,
    )


def staff_assertion(sub=None):
    return Assertion(sub=sub or uuid.uuid4(), jti=uuid.uuid4().hex, scope="staff", email="staff@example.test", mfa=True)


def memberships(db, user):
    return db.query(UserWorkspaceMembership).filter_by(user_id=user.id).all()


def test_creates_shadow_user_and_membership(db_session):
    ws = workspace(db_session)
    a = client_assertion(ws, role="manager")
    user = sync_shadow_user(db_session, a)
    assert (user.sso_subject, user.auth_source, user.role, user.is_active) == (a.sub, "sso", "viewer", True)
    assert user.email == "person@example.test"
    (m,) = memberships(db_session, user)
    assert (m.workspace_id, m.role, m.source) == (ws.id, "operator", "sso")


def test_second_exchange_is_idempotent_and_updates_role(db_session):
    ws = workspace(db_session)
    sub = uuid.uuid4()
    first = sync_shadow_user(db_session, client_assertion(ws, role="viewer", sub=sub))
    second = sync_shadow_user(db_session, client_assertion(ws, role="owner", sub=sub))
    assert first.id == second.id
    (m,) = memberships(db_session, second)
    assert m.role == "owner"
    assert db_session.query(User).filter_by(sso_subject=sub).count() == 1


@pytest.mark.parametrize("org_role,many_role", sorted(ORG_TO_WORKSPACE_ROLE.items()))
def test_role_mapping(db_session, org_role, many_role):
    ws = workspace(db_session)
    user = sync_shadow_user(db_session, client_assertion(ws, role=org_role))
    assert memberships(db_session, user)[0].role == many_role


def test_mapping_is_exactly_as_designed():
    assert ORG_TO_WORKSPACE_ROLE == {
        "owner": "owner", "admin": "admin", "manager": "operator", "agent": "viewer", "viewer": "viewer",
    }


def test_membership_moves_to_the_new_workspace_and_local_rows_survive(db_session):
    ws_a, ws_b, ws_local = workspace(db_session), workspace(db_session), workspace(db_session)
    sub = uuid.uuid4()
    user = sync_shadow_user(db_session, client_assertion(ws_a, sub=sub))
    db_session.add(UserWorkspaceMembership(user_id=user.id, workspace_id=ws_local.id, role="viewer", source="local"))
    db_session.flush()
    sync_shadow_user(db_session, client_assertion(ws_b, sub=sub))
    rows = {(m.workspace_id, m.source) for m in memberships(db_session, user)}
    assert rows == {(ws_b.id, "sso"), (ws_local.id, "local")}


def test_staff_gets_global_admin_and_no_sso_memberships(db_session):
    ws = workspace(db_session)
    sub = uuid.uuid4()
    client = sync_shadow_user(db_session, client_assertion(ws, sub=sub))
    assert client.role == "viewer" and len(memberships(db_session, client)) == 1
    staff = sync_shadow_user(db_session, staff_assertion(sub))
    assert staff.id == client.id and staff.role == "admin" and memberships(db_session, staff) == []


def test_workspace_mapping_mismatch_and_unmapped_are_refused(db_session):
    ws = workspace(db_session)
    wrong_org = Assertion(
        sub=uuid.uuid4(), jti=uuid.uuid4().hex, scope="client", email=None, mfa=True,
        org=uuid.uuid4(), workspace=ws.id, role="admin",
    )
    with pytest.raises(SSOAssertionError) as e:
        sync_shadow_user(db_session, wrong_org)
    assert e.value.reason == "workspace_mapping_mismatch"
    ws.saas_tenant_id = None
    db_session.flush()
    with pytest.raises(SSOAssertionError) as e:
        sync_shadow_user(db_session, client_assertion(ws))
    assert e.value.reason == "workspace_mapping_mismatch"
    missing = Assertion(
        sub=uuid.uuid4(), jti=uuid.uuid4().hex, scope="client", email=None, mfa=True,
        org=uuid.uuid4(), workspace=uuid.uuid4(), role="admin",
    )
    with pytest.raises(SSOAssertionError):
        sync_shadow_user(db_session, missing)


def test_email_collision_never_links_to_the_existing_user(db_session):
    local = User(email="person@example.test", password_hash="x", role="admin", is_active=True)
    db_session.add(local)
    db_session.flush()
    ws = workspace(db_session)
    a = client_assertion(ws)
    shadow = sync_shadow_user(db_session, a)
    assert shadow.id != local.id
    assert shadow.email == f"{a.sub}@sso.invalid"
    assert local.sso_subject is None and local.auth_source == "local"
    assert memberships(db_session, local) == []


def test_inactive_shadow_is_refused(db_session):
    ws = workspace(db_session)
    sub = uuid.uuid4()
    user = sync_shadow_user(db_session, client_assertion(ws, sub=sub))
    user.is_active = False
    db_session.flush()
    with pytest.raises(SSOAssertionError) as e:
        sync_shadow_user(db_session, client_assertion(ws, sub=sub))
    assert e.value.reason == "user_inactive"


def test_shadow_password_hash_never_verifies_and_never_raises(db_session):
    ws = workspace(db_session)
    user = sync_shadow_user(db_session, client_assertion(ws))
    assert user.password_hash.startswith("$argon2")
    for guess in ["", "password", "!", user.email, str(user.sso_subject)]:
        assert verify_password(guess, user.password_hash) is False


def _lose_the_race(monkeypatch):
    """First lookup misses (the other request has not committed yet), later ones see the row."""
    import app.services.sso_session as mod

    real = mod._find_by_subject
    calls = {"n": 0}

    def racing(db, sub):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(db, sub)

    monkeypatch.setattr(mod, "_find_by_subject", racing)


def test_concurrent_first_exchange_for_the_same_sub_reuses_the_winner(db_session, monkeypatch):
    ws = workspace(db_session)
    a = client_assertion(ws)
    winner = User(
        email="winner@example.test", password_hash="x", role="viewer", is_active=True,
        sso_subject=a.sub, auth_source="sso",
    )
    db_session.add(winner)
    db_session.flush()
    _lose_the_race(monkeypatch)
    user = sync_shadow_user(db_session, a)
    assert user.id == winner.id
    assert len(memberships(db_session, user)) == 1
    assert db_session.query(User).filter_by(sso_subject=a.sub).count() == 1


def test_race_loser_never_revives_an_inactive_winner(db_session, monkeypatch):
    ws = workspace(db_session)
    a = client_assertion(ws)
    db_session.add(User(
        email="winner@example.test", password_hash="x", role="viewer", is_active=False,
        sso_subject=a.sub, auth_source="sso",
    ))
    db_session.flush()
    _lose_the_race(monkeypatch)
    with pytest.raises(SSOAssertionError) as e:
        sync_shadow_user(db_session, a)
    assert e.value.reason == "user_inactive"


def test_unresolvable_insert_conflict_is_a_refusal_not_a_500(db_session, monkeypatch):
    import app.services.sso_session as mod

    db_session.add(User(email="taken@example.test", password_hash="x", role="viewer", is_active=True))
    db_session.flush()
    monkeypatch.setattr(mod, "_shadow_email", lambda db, a: "taken@example.test")
    with pytest.raises(SSOAssertionError) as e:
        sync_shadow_user(db_session, client_assertion(workspace(db_session)))
    assert e.value.reason == "user_conflict"
    # The request transaction is still usable afterwards.
    assert db_session.query(User).filter_by(email="taken@example.test").count() == 1
