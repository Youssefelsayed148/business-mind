from uuid import uuid4

from app.core.security import hash_password
from app.models.user import User
from app.models.user_workspace_membership import UserWorkspaceMembership
from app.models.workspace import Workspace
from app.models.instagram_account import InstagramAccount
from app.models.lead import Lead
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.meta_token import MetaToken
from app.models.saas_forward_event import SaasForwardEvent
from app.models.saas_outbound_message import SaasOutboundMessage
from app.models.webhook_event import WebhookEvent


def _account_data(db, suffix):
    workspace = Workspace(name=suffix, slug=suffix)
    db.add(workspace)
    db.flush()
    account = InstagramAccount(workspace_id=workspace.id, ig_user_id="account-" + suffix)
    db.add(account)
    db.flush()
    lead = Lead(workspace_id=workspace.id, instagram_account_id=account.id, ig_user_id="customer-" + suffix)
    db.add(lead)
    db.flush()
    conversation = Conversation(workspace_id=workspace.id, lead_id=lead.id, instagram_account_id=account.id)
    db.add(conversation)
    db.flush()
    message = Message(lead_id=lead.id, conversation_id=conversation.id, content="private message")
    db.add(message)
    db.flush()
    token = MetaToken(instagram_account_id=account.id, access_token="synthetic-encrypted-value")
    forward = SaasForwardEvent(event_id=str(uuid4()), ordering_key=str(conversation.id), platform="instagram", channel_id=account.id, event_type="message.received", payload={"text": "private message"})
    outbound = SaasOutboundMessage(connection_id=str(uuid4()), message_id=str(uuid4()), platform="instagram", channel_id=account.id, kind="reply", message_pk=message.id)
    db.add_all([token, forward, outbound])
    db.commit()
    return account, lead, conversation, message, token, forward, outbound


def _login(client, db, role, workspace_id):
    user = User(email=role + "@hard-delete.test", name=role, role=role, password_hash=hash_password("test-password"), is_active=True)
    db.add(user)
    db.flush()
    db.add(UserWorkspaceMembership(user_id=user.id, workspace_id=workspace_id, role=role))
    db.commit()
    response = client.post("/auth/login", data={"username": user.email, "password": "test-password"})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"], "X-Workspace-Id": str(workspace_id)}


def test_hard_delete_removes_conversations_and_delegation_data_only_for_account(client, db_session):
    target = _account_data(db_session, "target")
    other = _account_data(db_session, "other")
    headers = _login(client, db_session, "owner", target[0].workspace_id)
    account_id = target[0].id
    target_ig_id, other_ig_id = target[0].ig_user_id, other[0].ig_user_id
    target_rows = [(type(row), row.id) for row in target]
    other_rows = [(type(row), row.id) for row in other]
    only_target = WebhookEvent(provider="meta", external_event_id="target-only", payload={"object": "instagram", "entry": [{"id": target_ig_id, "messaging": [{"text": "private"}]}]})
    mixed = WebhookEvent(provider="meta", external_event_id="mixed", payload={"object": "instagram", "entry": [{"id": target_ig_id}, {"id": other_ig_id, "changes": []}, None]})
    unrelated = WebhookEvent(provider="meta", external_event_id="facebook", payload={"object": "page", "entry": [{"id": target_ig_id}]})
    db_session.add_all([only_target, mixed, unrelated])
    db_session.commit()
    only_target_id, mixed_id, unrelated_id = only_target.id, mixed.id, unrelated.id
    response = client.delete(f"/instagram/accounts/{account_id}/hard", headers=headers)
    assert response.status_code == 200
    db_session.expire_all()
    # Query rows rather than the session identity map after bulk deletes.
    for model, row_id in target_rows:
        assert db_session.query(model).filter(model.id == row_id).count() == 0
    for model, row_id in other_rows:
        assert db_session.query(model).filter(model.id == row_id).count() == 1
    assert db_session.get(WebhookEvent, only_target_id).payload is None
    assert db_session.get(WebhookEvent, only_target_id).processing_status == "skipped"
    assert db_session.get(WebhookEvent, mixed_id).payload["entry"] == [{"id": other_ig_id, "changes": []}, None]
    assert db_session.get(WebhookEvent, unrelated_id).payload["object"] == "page"
    assert client.delete(f"/instagram/accounts/{account_id}/hard", headers=headers).status_code == 404


def test_hard_delete_requires_owner_permission(client, db_session):
    account = _account_data(db_session, "protected")[0]
    account_id = account.id
    headers = _login(client, db_session, "admin", account.workspace_id)
    assert client.delete(f"/instagram/accounts/{account_id}/hard", headers=headers).status_code == 403
    assert db_session.get(InstagramAccount, account_id) is not None


def test_hard_delete_cannot_cross_workspace(client, db_session):
    target = _account_data(db_session, "tenant-a")[0]
    other = _account_data(db_session, "tenant-b")[0]
    target_id = target.id
    headers = _login(client, db_session, "owner", other.workspace_id)
    assert client.delete(f"/instagram/accounts/{target_id}/hard", headers=headers).status_code == 404
    assert db_session.get(InstagramAccount, target_id) is not None
    headers["X-Workspace-Id"] = str(target.workspace_id)
    assert client.delete(f"/instagram/accounts/{target_id}/hard", headers=headers).status_code == 403
    assert db_session.get(InstagramAccount, target_id) is not None
