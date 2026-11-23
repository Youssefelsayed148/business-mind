import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from tests.conftest import skip_if_no_db


@skip_if_no_db
def test_login_returns_token(client: TestClient, db_session: Session):
    user = User(
        id=__import__("uuid").uuid4(),
        email="login@test.com",
        name="Login User",
        password_hash=hash_password("secret"),
        role="user",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    response = client.post(
        "/auth/login",
        data={"username": "login@test.com", "password": "secret"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@skip_if_no_db
def test_auth_me_returns_user(client: TestClient, db_session: Session):
    user = User(
        id=__import__("uuid").uuid4(),
        email="me@test.com",
        name="Me User",
        password_hash=hash_password("secret"),
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()

    token_response = client.post(
        "/auth/login",
        data={"username": "me@test.com", "password": "secret"},
    )
    token = token_response.json()["access_token"]

    response = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "me@test.com"
    assert data["role"] == "admin"
    assert data["name"] == "Me User"


@skip_if_no_db
def test_login_invalid_credentials(client: TestClient):
    response = client.post(
        "/auth/login",
        data={"username": "bad@test.com", "password": "wrong"},
    )
    assert response.status_code == 401


@skip_if_no_db
def test_logout(client: TestClient):
    response = client.post("/auth/logout")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
