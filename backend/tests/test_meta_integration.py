from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from app.models.workspace import Workspace
from app.services.token_service import get_decrypted_token
from tests.conftest import skip_if_no_db


@skip_if_no_db
def test_mock_meta_connect_creates_account_and_encrypted_token(
    client: TestClient, db_session: Session
):
    # Create default workspace and user
    ws = Workspace(id=__import__("uuid").uuid4(), name="Default", slug="default")
    db_session.add(ws)
    user = User(
        id=__import__("uuid").uuid4(),
        email="meta@test.com",
        name="Meta User",
        password_hash=hash_password("secret"),
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    token_resp = client.post(
        "/auth/login",
        data={"username": "meta@test.com", "password": "secret"},
    )
    token = token_resp.json()["access_token"]

    response = client.post(
        "/meta/connect/mock",
        json={
            "ig_user_id": "123456789",
            "username": "testhandle",
            "account_type": "BUSINESS",
            "access_token": "test_access_token_value",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "connected"
    assert data["ig_user_id"] == "123456789"

    # Verify token is encrypted in DB
    from app.models.instagram_account import InstagramAccount

    account = db_session.query(InstagramAccount).filter(InstagramAccount.ig_user_id == "123456789").first()
    assert account is not None
    assert account.ig_username == "testhandle"
    assert account.status == "connected"

    decrypted = get_decrypted_token(db_session, account.id)
    assert decrypted == "test_access_token_value"


@skip_if_no_db
def test_token_is_not_plaintext_in_db(client: TestClient, db_session: Session):
    from app.models.instagram_account import InstagramAccount
    from app.models.meta_token import MetaToken

    ws = Workspace(id=__import__("uuid").uuid4(), name="Default", slug="default")
    db_session.add(ws)
    user = User(
        id=__import__("uuid").uuid4(),
        email="plaintext@test.com",
        name="Plaintext User",
        password_hash=hash_password("secret"),
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    token_resp = client.post(
        "/auth/login",
        data={"username": "plaintext@test.com", "password": "secret"},
    )
    token = token_resp.json()["access_token"]

    client.post(
        "/meta/connect/mock",
        json={
            "ig_user_id": "999888777",
            "username": "plaincheck",
            "account_type": "BUSINESS",
            "access_token": "secret_token_abc",
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    account = db_session.query(InstagramAccount).filter(InstagramAccount.ig_user_id == "999888777").first()
    meta_token = (
        db_session.query(MetaToken)
        .filter(MetaToken.instagram_account_id == account.id)
        .first()
    )
    assert meta_token is not None
    assert meta_token.access_token != "secret_token_abc"
    assert "secret_token_abc" not in meta_token.access_token
