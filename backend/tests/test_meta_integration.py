"""The mock connector is development-only; test token storage without it."""
from uuid import uuid4

from app.models.instagram_account import InstagramAccount
from app.models.meta_token import MetaToken
from app.models.workspace import Workspace
from app.services.token_service import get_decrypted_token, store_encrypted_token


def test_mock_meta_connect_is_unavailable_in_test(client, db_session):
    response = client.post("/meta/connect/mock", json={
        "ig_user_id": "test-account", "username": "test", "account_type": "BUSINESS",
        "access_token": "synthetic-token",
    })
    assert response.status_code == 404
    assert db_session.query(InstagramAccount).count() == 0
    assert db_session.query(MetaToken).count() == 0


def test_token_is_not_plaintext_in_db(db_session):
    workspace = Workspace(id=uuid4(), name="Token test", slug="token-test")
    db_session.add(workspace)
    db_session.flush()
    account = InstagramAccount(workspace_id=workspace.id, ig_user_id="test-token-account")
    db_session.add(account)
    db_session.flush()
    store_encrypted_token(db_session, workspace.id, account.id, "synthetic-secret-token")
    token = db_session.query(MetaToken).filter(MetaToken.instagram_account_id == account.id).one()
    assert token.access_token != "synthetic-secret-token"
    assert "synthetic-secret-token" not in token.access_token
    assert get_decrypted_token(db_session, account.id) == "synthetic-secret-token"
