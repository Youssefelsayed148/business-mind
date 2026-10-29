import base64
import hashlib
import hmac
import json
from uuid import uuid4

import pytest

from app.core.config import settings
from app.models.workspace import Workspace
from app.models.facebook_page import FacebookPage
from app.models.facebook_token import FacebookToken
from app.models.instagram_account import InstagramAccount
from app.models.meta_token import MetaToken
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_token import WhatsappToken
from app.models.meta_authorization import MetaAuthorization
from app.models.data_deletion_request import DataDeletionRequest
from app.models.saas_forward_event import SaasForwardEvent
from app.services import meta_compliance as service
from tests.conftest import skip_if_no_db

pytestmark = skip_if_no_db


@pytest.fixture(autouse=True)
def app_namespaces(monkeypatch):
    monkeypatch.setattr(settings, "META_APP_ID", "instagram-app")
    monkeypatch.setattr(settings, "META_APP_SECRET", "test-instagram-secret")
    monkeypatch.setattr(settings, "FACEBOOK_APP_ID", "facebook-app")
    monkeypatch.setattr(settings, "FACEBOOK_APP_SECRET", "test-facebook-secret")


def _b64(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _signed(subject="12345", *, app="facebook", payload=None, secret=None):
    payload = payload if payload is not None else {"algorithm": "HMAC-SHA256", "user_id": subject, "issued_at": 1234}
    encoded = _b64(json.dumps(payload, separators=(",", ":")).encode())
    key = secret or service.app_credentials(app)[1]
    return _b64(hmac.new(key.encode(), encoded.encode(), hashlib.sha256).digest()) + "." + encoded


def _workspace(db):
    row = Workspace(id=uuid4(), name="Test", slug=str(uuid4()))
    db.add(row)
    db.flush()
    return row


def _channel(db, platform="facebook", workspace=None):
    workspace = workspace or _workspace(db)
    model, token, fk = service.CHANNELS[platform]
    external_key = {"facebook": "page_id", "instagram": "ig_user_id", "whatsapp": "phone_number_id"}[platform]
    row = model(id=uuid4(), workspace_id=workspace.id, status="connected", ai_enabled=True,
                saas_delegation_enabled=True, **{external_key: str(uuid4())})
    db.add(row)
    db.flush()
    db.add(token(**{fk: row.id}, access_token="synthetic-encrypted-test-value"))
    db.flush()
    return row, workspace


def _map(db, account, workspace, platform="facebook", subject="12345"):
    service.record_authorization(db, app="instagram" if platform == "instagram" else "facebook",
                                 subject=subject, workspace_id=workspace.id, platform=platform,
                                 channel_id=account.id, verified_provider_identity=True)


@pytest.mark.parametrize("value", ["", "x", "..", "a.b", "a.b.c", "?.abc", "a" * 17000])
def test_malformed_signed_request_rejected(value):
    with pytest.raises(service.InvalidSignedRequest):
        service.verify_signed_request(value, settings.facebook_app_secret)


@pytest.mark.parametrize("payload", [
    [], None, {"algorithm": "none", "user_id": "123"},
    {"algorithm": "HMAC-SHA256", "user_id": 123},
    {"algorithm": "HMAC-SHA256", "user_id": "page:123"},
    {"algorithm": "HMAC-SHA256", "user_id": "123", "issued_at": True},
    {"algorithm": "HMAC-SHA256", "user_id": "123", "issued_at": -1},
])
def test_authenticated_invalid_payload_rejected(payload):
    # None gets encoded explicitly here, rather than using the helper's default.
    encoded = _b64(json.dumps(payload).encode())
    value = _b64(hmac.new(settings.facebook_app_secret.encode(), encoded.encode(), hashlib.sha256).digest()) + "." + encoded
    with pytest.raises(service.InvalidSignedRequest):
        service.verify_signed_request(value, settings.facebook_app_secret)


def test_duplicate_json_keys_rejected():
    encoded = _b64(b'{"algorithm":"HMAC-SHA256","user_id":"123","user_id":"456"}')
    value = _b64(hmac.new(settings.facebook_app_secret.encode(), encoded.encode(), hashlib.sha256).digest()) + "." + encoded
    with pytest.raises(service.InvalidSignedRequest):
        service.verify_signed_request(value, settings.facebook_app_secret)


@pytest.mark.parametrize("platform", ["facebook", "instagram", "whatsapp"])
def test_deauthorize_physically_deletes_only_verified_grant_tokens(client, db_session, platform):
    account, workspace = _channel(db_session, platform)
    other, other_workspace = _channel(db_session, platform)
    _map(db_session, account, workspace, platform)
    _map(db_session, other, other_workspace, platform, subject="999")
    app = "instagram" if platform == "instagram" else "facebook"
    signed = _signed(app=app)
    for _ in range(2):
        response = client.post(f"/meta/compliance/{app}/deauthorize", data={"signed_request": signed})
        assert response.status_code == 200
    db_session.expire_all()
    assert account.status == "disconnected" and not account.saas_delegation_enabled and not account.ai_enabled
    assert other.status == "connected" and other.saas_delegation_enabled
    _, token, fk = service.CHANNELS[platform]
    assert db_session.query(token).filter(getattr(token, fk) == account.id).count() == 0
    assert db_session.query(token).filter(getattr(token, fk) == other.id).count() == 1
    assert db_session.query(DataDeletionRequest).count() == 1


def test_page_id_equal_to_callback_subject_never_infers_authorization(client, db_session):
    account, _ = _channel(db_session)
    account.page_id = "12345"
    db_session.flush()
    response = client.post("/meta/compliance/facebook/deauthorize", data={"signed_request": _signed()})
    assert response.status_code == 200
    db_session.expire_all()
    assert account.status == "connected"
    assert db_session.query(FacebookToken).count() == 1
    assert db_session.query(DataDeletionRequest).one().status == "operator_action"


def test_cross_workspace_forged_mapping_does_not_disconnect_other_workspace(client, db_session):
    account, _ = _channel(db_session)
    wrong_workspace = _workspace(db_session)
    db_session.add(MetaAuthorization(app_id=settings.facebook_app_id,
        subject_digest=service.subject_digest(settings.facebook_app_id, "12345"),
        workspace_id=wrong_workspace.id, platform="facebook", channel_id=account.id,
        verification_source="synthetic-invalid-mapping"))
    db_session.flush()
    response = client.post("/meta/compliance/facebook/deauthorize", data={"signed_request": _signed()})
    assert response.status_code == 200
    db_session.expire_all()
    assert account.status == "connected"
    assert db_session.query(FacebookToken).count() == 1


def test_invalid_signature_has_no_side_effects_or_identity_oracle(client, db_session):
    account, workspace = _channel(db_session)
    _map(db_session, account, workspace)
    response = client.post("/meta/compliance/facebook/deauthorize", data={"signed_request": _signed(secret="wrong")})
    assert response.status_code == 403 and response.json() == {"detail": "Invalid callback"}
    assert db_session.query(DataDeletionRequest).count() == 0
    assert db_session.query(FacebookToken).count() == 1
    assert account.status == "connected"


def test_app_secrets_and_namespaces_are_separate(client, db_session):
    account, workspace = _channel(db_session)
    _map(db_session, account, workspace)
    response = client.post("/meta/compliance/instagram/deauthorize", data={"signed_request": _signed()})
    assert response.status_code == 403
    assert account.status == "connected"


def test_deletion_receipt_is_durable_idempotent_and_contains_no_pii(client, db_session):
    value = _signed()
    first = client.post("/meta/compliance/facebook/data-deletion", data={"signed_request": value})
    second = client.post("/meta/compliance/facebook/data-deletion", data={"signed_request": value})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    code = first.json()["confirmation_code"]
    assert len(code) == 43
    assert "12345" not in first.text
    assert first.headers["cache-control"] == "no-store"
    page = client.get(f"/meta/data-deletion/status/{code}")
    assert page.status_code == 200 and "pending" in page.text and "12345" not in page.text
    assert page.headers["referrer-policy"] == "no-referrer"
    row = db_session.query(DataDeletionRequest).one()
    assert row.status == "operator_action" and row.completed_at is None
    assert row.subject_digest != "12345"
    assert client.get("/meta/data-deletion/status/invalid").status_code == 404


def test_completion_requires_both_application_confirmations(client, db_session):
    client.post("/meta/compliance/facebook/data-deletion", data={"signed_request": _signed()})
    row = db_session.query(DataDeletionRequest).one()
    with pytest.raises(ValueError):
        service.complete_request(db_session, row.id, many_erasure_confirmed=True, saas_erasure_confirmed=False)
    assert row.status == "operator_action"
    service.complete_request(db_session, row.id, many_erasure_confirmed=True, saas_erasure_confirmed=True)
    db_session.flush()
    assert "completed after operator verification" in client.get(f"/meta/data-deletion/status/{row.confirmation_code}").text


def test_operator_mapping_rejects_wrong_workspace_or_missing_provider_proof(db_session):
    account, _ = _channel(db_session)
    other = _workspace(db_session)
    with pytest.raises(ValueError):
        service.record_authorization(db_session, app="facebook", subject="123", workspace_id=other.id,
                                     platform="facebook", channel_id=account.id, verified_provider_identity=True)
    with pytest.raises(ValueError):
        service.record_authorization(db_session, app="facebook", subject="123", workspace_id=other.id,
                                     platform="facebook", channel_id=account.id, verified_provider_identity=False)
    assert db_session.query(MetaAuthorization).count() == 0


def test_callback_before_mapping_is_reconciled_by_verified_operator_mapping(client, db_session):
    account, workspace = _channel(db_session)
    client.post("/meta/compliance/facebook/deauthorize", data={"signed_request": _signed()})
    assert account.status == "connected"
    _map(db_session, account, workspace)
    db_session.flush()
    assert account.status == "disconnected"
    assert db_session.query(FacebookToken).count() == 0


def test_deauthorize_preserves_erasure_outbox_but_drops_ordinary_forwards(client, db_session):
    account, workspace = _channel(db_session)
    _map(db_session, account, workspace)
    for event_type in ("contact.erasure", "message.received"):
        db_session.add(SaasForwardEvent(event_id=str(uuid4()), ordering_key=str(uuid4()),
            platform="facebook", channel_id=account.id, event_type=event_type, payload={"synthetic": True}))
    db_session.flush()
    client.post("/meta/compliance/facebook/deauthorize", data={"signed_request": _signed()})
    rows = {r.event_type: r for r in db_session.query(SaasForwardEvent).all()}
    assert rows["contact.erasure"].status == "pending"
    assert rows["message.received"].status == "dropped" and rows["message.received"].payload == {}


def test_callback_rejects_oversize_duplicate_fields_and_json(client, db_session):
    assert client.post("/meta/compliance/facebook/deauthorize", content="x" * 18000,
                       headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 413
    assert client.post("/meta/compliance/facebook/deauthorize", content="signed_request=a&signed_request=b",
                       headers={"Content-Type": "application/x-www-form-urlencoded"}).status_code == 403
    assert client.post("/meta/compliance/facebook/deauthorize", json={"signed_request": _signed()}).status_code == 403
    assert db_session.query(DataDeletionRequest).count() == 0


def test_completed_callback_replay_does_not_revoke_new_verified_grant(client, db_session):
    account, workspace = _channel(db_session)
    _map(db_session, account, workspace)
    signed = _signed()
    client.post("/meta/compliance/facebook/deauthorize", data={"signed_request": signed})
    row = db_session.query(DataDeletionRequest).one()
    service.complete_request(db_session, row.id, many_erasure_confirmed=True, saas_erasure_confirmed=True)
    db_session.flush()
    account.status = "connected"
    account.saas_delegation_enabled = True
    db_session.add(FacebookToken(facebook_page_id=account.id, access_token="synthetic-new-encrypted-grant"))
    db_session.flush()
    _map(db_session, account, workspace)
    response = client.post("/meta/compliance/facebook/deauthorize", data={"signed_request": signed})
    assert response.status_code == 200
    db_session.expire_all()
    assert account.status == "connected" and account.saas_delegation_enabled
    assert db_session.query(FacebookToken).count() == 1


def test_cli_requires_explicit_operator_database_variable(monkeypatch, capsys):
    monkeypatch.delenv("META_COMPLIANCE_DATABASE_URL", raising=False)
    assert service.main(["list-pending"]) == 1
    assert service.main(["list-pending", "--database-url-env", "DATABASE_URL"]) == 1
    assert "unreachable" not in capsys.readouterr().out


def test_cli_engine_initialization_errors_do_not_leak_database_credentials(monkeypatch, capsys):
    marker = "synthetic-secret-do-not-print"
    monkeypatch.setenv("META_COMPLIANCE_DATABASE_URL", "postgresql://operator:" + marker + "@invalid/test")

    def fail_engine(_url):
        raise ValueError(marker)

    monkeypatch.setattr(service, "create_engine", fail_engine)
    assert service.main(["list-pending"]) == 1
    output = capsys.readouterr()
    assert "could not be verified or saved" in output.out
    assert marker not in output.out + output.err


def test_cli_defaults_to_rollback_and_requires_completion_attestations(monkeypatch, capsys):
    import os
    monkeypatch.setenv("META_COMPLIANCE_DATABASE_URL", os.environ["TEST_DATABASE_URL"])
    assert service.main(["list-pending"]) == 0
    assert "DRY RUN: no changes saved" in capsys.readouterr().out
    assert service.main(["complete", "--request-id", str(uuid4()), "--apply"]) == 1
    assert "could not be verified or saved" in capsys.readouterr().out
