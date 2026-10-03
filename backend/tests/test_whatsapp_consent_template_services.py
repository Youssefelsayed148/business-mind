from __future__ import annotations

from uuid import uuid4

import pytest

from app.integrations.meta.whatsapp_management_client import WhatsappManagementResult
from app.models.user import User
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_consent_event import WhatsappConsentEvent
from app.models.whatsapp_contact import WhatsappContact
from app.models.whatsapp_template import WhatsappTemplate
from app.models.workspace import Workspace
from app.services.whatsapp_consent_service import (
    ConsentValidationError,
    grant,
    import_contacts,
)
from app.services.whatsapp_template_service import (
    TemplateValidationError,
    delete_template_by_name,
    render_template_components,
    sync_templates,
    validate_template_variables,
)
from tests.conftest import skip_if_no_db


def _seed_account(db):
    workspace = Workspace(name="Services", slug=f"services-{uuid4().hex}")
    user = User(email=f"{uuid4().hex}@example.test", password_hash="x", role="admin")
    db.add_all([workspace, user])
    db.flush()
    account = WhatsappAccount(
        workspace_id=workspace.id,
        phone_number_id=f"phone-{uuid4().hex}",
        whatsapp_business_account_id="waba-services",
    )
    db.add(account)
    db.flush()
    return workspace, user, account


def _contact(db, account, wa_id="16315551234", consent="unknown"):
    contact = WhatsappContact(
        workspace_id=account.workspace_id,
        whatsapp_account_id=account.id,
        wa_id=wa_id,
        marketing_consent=consent,
    )
    db.add(contact)
    db.flush()
    return contact


@skip_if_no_db
def test_unattested_reimport_preserves_existing_opt_in(db_session):
    _, user, account = _seed_account(db_session)
    contact = _contact(db_session, account, consent="opted_in")

    import_contacts(
        db_session,
        account=account,
        csv_data=f"wa_id,name\n{contact.wa_id},Existing\n",
        filename="unattested.csv",
        actor=user,
    )

    assert contact.marketing_consent == "opted_in"
    assert contact.consent_at is None


@skip_if_no_db
def test_attested_import_skips_opted_out_and_records_evidence(db_session):
    _, user, account = _seed_account(db_session)
    contact = _contact(db_session, account, consent="opted_out")

    import_contacts(
        db_session,
        account=account,
        csv_data=f"wa_id\n{contact.wa_id}\n",
        filename="attested.csv",
        actor=user,
        attestation_text="I attest that these contacts opted in.",
    )

    event = db_session.query(WhatsappConsentEvent).filter_by(contact_id=contact.id).one()
    assert contact.marketing_consent == "opted_out"
    assert event.evidence["skipped_opted_out"] is True


@skip_if_no_db
def test_manual_grant_requires_actor_and_nonempty_proof(db_session):
    _, user, account = _seed_account(db_session)
    contact = _contact(db_session, account)

    with pytest.raises(ConsentValidationError, match="manual_consent_actor_required"):
        grant(db_session, contact=contact, evidence={"note": "Phone confirmation"})
    with pytest.raises(ConsentValidationError, match="manual_consent_proof_required"):
        grant(db_session, contact=contact, actor=user, evidence={"note": "  "})

    grant(
        db_session,
        contact=contact,
        actor=user,
        evidence={"proof": "Signed paper form #42"},
    )
    event = db_session.query(WhatsappConsentEvent).filter_by(contact_id=contact.id).one()
    assert contact.marketing_consent == "opted_in"
    assert event.event_type == "opt_in"
    assert event.actor_user_id == user.id


@skip_if_no_db
def test_resubscribe_requires_evidence_and_uses_resubscribe_event(db_session):
    _, _, account = _seed_account(db_session)
    contact = _contact(db_session, account, consent="opted_out")

    with pytest.raises(ConsentValidationError, match="resubscribe_evidence_required"):
        grant(db_session, contact=contact, source="web_form")

    grant(
        db_session,
        contact=contact,
        source="web_form",
        evidence={"proof": "Signed opt-in token", "url": "https://example.test/opt-in"},
    )
    event = db_session.query(WhatsappConsentEvent).filter_by(contact_id=contact.id).one()
    assert contact.marketing_consent == "opted_in"
    assert event.event_type == "resubscribe"


def _variable_template() -> WhatsappTemplate:
    return WhatsappTemplate(
        workspace_id=uuid4(),
        whatsapp_account_id=uuid4(),
        name="shipping_update",
        language="en_US",
        category="utility",
        status="approved",
        components=[
            {"type": "HEADER", "format": "TEXT", "text": "Order {{1}}"},
            {"type": "BODY", "text": "Hello {{2}}, delivery is {{3}}."},
            {"type": "FOOTER", "text": "Thank you"},
        ],
    )


def test_template_variable_validation_and_rendering():
    template = _variable_template()
    validate_template_variables(template, {1: "A-42", 2: "Ada", 3: "tomorrow"})
    assert render_template_components(template, ["A-42", "Ada", "tomorrow"]) == [
        {"type": "header", "parameters": [{"type": "text", "text": "A-42"}]},
        {
            "type": "body",
            "parameters": [
                {"type": "text", "text": "Ada"},
                {"type": "text", "text": "tomorrow"},
            ],
        },
    ]

    with pytest.raises(TemplateValidationError, match="template_variable_count_mismatch"):
        validate_template_variables(template, ["A-42", "Ada"])
    with pytest.raises(TemplateValidationError, match="template_variable_value_empty"):
        validate_template_variables(template, ["A-42", " ", "tomorrow"])

    template.components[1]["text"] = "Hello {{3}}"
    with pytest.raises(TemplateValidationError, match="template_variables_not_sequential"):
        validate_template_variables(template, ["A-42", "Ada", "tomorrow"])


class _ManagementClient:
    def __init__(self, *, list_result=None, delete_result=None):
        self.list_result = list_result
        self.delete_result = delete_result
        self.delete_calls = 0

    def list_templates(self, *_args):
        return self.list_result

    def delete_template_by_name(self, *_args):
        self.delete_calls += 1
        return self.delete_result


@skip_if_no_db
def test_sync_templates_updates_existing_and_imports_meta_only_template(db_session):
    _, _, account = _seed_account(db_session)
    existing = WhatsappTemplate(
        workspace_id=account.workspace_id,
        whatsapp_account_id=account.id,
        meta_template_id="old-id",
        name="shipping_update",
        language="en_US",
        category="utility",
        status="pending",
        components=[],
    )
    db_session.add(existing)
    db_session.flush()
    rows = [
        {
            "id": "meta-existing",
            "name": "shipping_update",
            "language": "en_US",
            "category": "UTILITY",
            "status": "APPROVED",
            "components": [{"type": "BODY", "text": "Ready"}],
        },
        {
            "id": "meta-direct",
            "name": "created_in_meta",
            "language": "ar",
            "category": "MARKETING",
            "status": "PAUSED",
            "components": [{"type": "BODY", "text": "Offer"}],
        },
    ]
    client = _ManagementClient(
        list_result=WhatsappManagementResult(success=True, data=rows)
    )

    result = sync_templates(
        db_session, account=account, access_token="token", client=client
    )

    assert (result.success, result.created, result.updated) == (True, 1, 1)
    assert existing.meta_template_id == "meta-existing"
    assert existing.status == "approved"
    imported = db_session.query(WhatsappTemplate).filter_by(name="created_in_meta").one()
    assert imported.workspace_id == account.workspace_id
    assert imported.category == "marketing"
    assert imported.status == "paused"


@skip_if_no_db
def test_sync_templates_failure_changes_nothing(db_session):
    _, _, account = _seed_account(db_session)
    template = WhatsappTemplate(
        workspace_id=account.workspace_id,
        whatsapp_account_id=account.id,
        name="unchanged",
        language="en_US",
        category="utility",
        status="approved",
        components=[],
    )
    db_session.add(template)
    db_session.flush()
    client = _ManagementClient(
        list_result=WhatsappManagementResult(success=False, error_message="Meta failed")
    )

    result = sync_templates(
        db_session, account=account, access_token="token", client=client
    )
    assert result.success is False
    assert result.error_message == "Meta failed"
    assert template.status == "approved"


@skip_if_no_db
def test_delete_success_marks_all_languages_deleted_and_failure_changes_nothing(db_session):
    _, _, account = _seed_account(db_session)
    rows = [
        WhatsappTemplate(
            workspace_id=account.workspace_id,
            whatsapp_account_id=account.id,
            name="seasonal_offer",
            language=language,
            category="marketing",
            status="approved",
            components=[],
        )
        for language in ("en_US", "ar")
    ]
    untouched = WhatsappTemplate(
        workspace_id=account.workspace_id,
        whatsapp_account_id=account.id,
        name="failed_delete",
        language="en_US",
        category="utility",
        status="approved",
        components=[],
    )
    db_session.add_all([*rows, untouched])
    db_session.flush()

    success_client = _ManagementClient(
        delete_result=WhatsappManagementResult(success=True, data={"success": True})
    )
    delete_template_by_name(
        db_session,
        account=account,
        name="seasonal_offer",
        access_token="token",
        client=success_client,
    )
    assert [row.status for row in rows] == ["deleted", "deleted"]

    failure_client = _ManagementClient(
        delete_result=WhatsappManagementResult(success=False, error_message="Meta failed")
    )
    delete_template_by_name(
        db_session,
        account=account,
        name="failed_delete",
        access_token="token",
        client=failure_client,
    )
    assert untouched.status == "approved"
