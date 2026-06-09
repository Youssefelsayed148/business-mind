import uuid

import pytest
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from app.models.workspace import Workspace
from tests.conftest import skip_if_no_db


@skip_if_no_db
def test_create_admin_script_creates_user(db_session: Session):
    from app.scripts.create_admin import create_admin, create_default_workspace

    workspace = create_default_workspace(db_session)
    assert workspace.slug == "default"

    user = create_admin(db_session, "admin@test.com", "admin123", "Admin")
    assert user.email == "admin@test.com"
    assert user.role == "admin"

    # Idempotent: running again should not duplicate
    user2 = create_admin(db_session, "admin@test.com", "admin123", "Admin")
    assert user2.id == user.id


@skip_if_no_db
def test_duplicate_workspace_slug_rejected(db_session: Session):
    ws1 = Workspace(id=uuid.uuid4(), name="First", slug="test-slug")
    db_session.add(ws1)
    db_session.commit()

    ws2 = Workspace(id=uuid.uuid4(), name="Second", slug="test-slug")
    db_session.add(ws2)
    with pytest.raises(Exception):
        db_session.commit()


@skip_if_no_db
def test_duplicate_user_email_rejected(db_session: Session):
    u1 = User(
        id=uuid.uuid4(),
        email="dup@test.com",
        name="User1",
        password_hash=hash_password("pass"),
        role="user",
    )
    db_session.add(u1)
    db_session.commit()

    u2 = User(
        id=uuid.uuid4(),
        email="dup@test.com",
        name="User2",
        password_hash=hash_password("pass"),
        role="user",
    )
    db_session.add(u2)
    with pytest.raises(Exception):
        db_session.commit()
