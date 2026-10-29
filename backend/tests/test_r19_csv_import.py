"""Many has strict E.164 CSV import, rather than the SaaS phone export exemption."""
import csv
import io

import pytest

from app.api.routes_dashboard import _csv_safe
from app.models.lead import Lead
from app.models.whatsapp_contact import WhatsappContact
from app.services.whatsapp_consent_service import import_contacts
from tests.test_contact_erasure import world


def test_csv_import_rejects_formula_phones_and_keeps_valid_in_workspace(db_session, world):
    channel = world.channels[("a", "whatsapp")]
    result = import_contacts(db_session, account=channel,
        csv_data="phone,name\n-1-1,unsafe\n=1+1,unsafe\n+SUM(A1),unsafe\n@SUM(A1),unsafe\n+201234567890,valid\n",
        filename="synthetic.csv", actor=world.user, attestation_text="Synthetic test consent")
    assert result.invalid == 4 and result.created == 1
    contacts = db_session.query(WhatsappContact).all()
    assert [(c.workspace_id, c.whatsapp_account_id, c.wa_id) for c in contacts] == [(channel.workspace_id, channel.id, "201234567890")]
    assert db_session.query(WhatsappContact).filter_by(workspace_id=world.other.id).count() == 0


@pytest.mark.parametrize("value", ["=SUM(A1)", "+SUM(A1)", "-1-1", "@SUM(A1)", "\tformula", "\rformula"])
def test_many_csv_cells_escape_formula_prefixes(value):
    assert _csv_safe(value) == "'" + value
    assert _csv_safe("201234567890") == "201234567890"
    assert _csv_safe("Customer") == "Customer"


def test_many_csv_export_guards_untrusted_names_and_ids(client, db_session, world):
    channel = world.channels[("a", "whatsapp")]
    channel.display_phone_number = "@unsafe account label"
    db_session.add(Lead(workspace_id=channel.workspace_id, platform="whatsapp", whatsapp_account_id=channel.id,
                        ig_user_id="-1-1", ig_username="=SUM(A1)", lead_source="cold_dm"))
    db_session.add(Lead(workspace_id=channel.workspace_id, platform="whatsapp", whatsapp_account_id=channel.id,
                        ig_user_id="201234567890", ig_username="Customer", lead_source="cold_dm"))
    db_session.commit()
    response = client.get("/leads/export.csv", headers=world.headers)
    assert response.status_code == 200
    rows = {row["username"]: row for row in csv.DictReader(io.StringIO(response.text))}
    assert rows["'=SUM(A1)"]["user_id"] == "'-1-1"
    assert rows["Customer"]["user_id"] == "201234567890"
    assert all(row["account"] == "'@unsafe account label" for row in rows.values())


@pytest.mark.parametrize("platform,fk", [
    ("instagram", "instagram_account_id"),
    ("facebook", "facebook_page_id"),
    ("whatsapp", "whatsapp_account_id"),
])
def test_csv_export_workspace_isolation(client, db_session, world, platform, fk):
    from app.core.security import create_access_token
    from app.models.user import User
    from app.models.user_workspace_membership import UserWorkspaceMembership

    other_user = User(email="csv-b@test.invalid", password_hash="unused", role="viewer", is_active=True)
    db_session.add(other_user)
    db_session.flush()
    db_session.add(UserWorkspaceMembership(user_id=other_user.id, workspace_id=world.other.id, role="viewer"))
    for side in ("a", "b"):
        channel = world.channels[(side, platform)]
        db_session.add(Lead(workspace_id=channel.workspace_id, platform=platform,
                            ig_user_id=f"private-{side}", ig_username=f"customer-{side}",
                            lead_source="cold_dm", **{fk: channel.id}))
    db_session.commit()
    for side, user, workspace in (("a", world.user, world.workspace), ("b", other_user, world.other)):
        headers = {"Authorization": "Bearer " + create_access_token(str(user.id)), "X-Workspace-Id": str(workspace.id)}
        response = client.get("/leads/export.csv", headers=headers)
        assert response.status_code == 200
        rows = list(csv.DictReader(io.StringIO(response.text)))
        assert [row["user_id"] for row in rows] == [f"private-{side}"]
        hidden = "b" if side == "a" else "a"
        assert f"customer-{hidden}" not in response.text
        assert f"private-{hidden}" not in response.text


def test_csv_export_requires_workspace_membership(client, world):
    from uuid import uuid4

    assert client.get("/leads/export.csv").status_code == 401
    headers = dict(world.headers)
    headers.pop("X-Workspace-Id")
    assert client.get("/leads/export.csv", headers=headers).status_code == 400
    for workspace, expected in (("invalid", 400), (str(world.other.id), 403), (str(uuid4()), 403)):
        headers["X-Workspace-Id"] = workspace
        response = client.get("/leads/export.csv", headers=headers)
        assert response.status_code == expected
        assert "text/csv" not in response.headers.get("content-type", "")


@pytest.mark.parametrize("platform,fk,label", [
    ("instagram", "instagram_account_id", "ig_username"),
    ("facebook", "facebook_page_id", "page_name"),
    ("whatsapp", "whatsapp_account_id", "display_phone_number"),
])
def test_csv_export_hides_foreign_resource_labels(client, db_session, world, platform, fk, label):
    from app.models.campaign import Campaign
    from app.models.facebook_campaign import FacebookCampaign
    from app.models.message import Message

    hidden_account = world.channels[("b", platform)]
    setattr(hidden_account, label, "hidden-account")
    hidden_campaign = Campaign(workspace_id=world.other.id,
        instagram_account_id=world.channels[("b", "instagram")].id, name="hidden-campaign")
    hidden_fb_campaign = FacebookCampaign(workspace_id=world.other.id,
        facebook_page_id=world.channels[("b", "facebook")].id, name="hidden-fb-campaign")
    db_session.add_all([hidden_campaign, hidden_fb_campaign])
    db_session.flush()
    # The schema permits inconsistent workspace FKs: labels must fail closed too.
    lead = Lead(workspace_id=world.workspace.id, platform=platform,
        ig_user_id="visible-customer", lead_source="campaign", **{fk: hidden_account.id})
    if platform != "facebook":
        lead.source_campaign_id = hidden_campaign.id
    db_session.add(lead)
    db_session.flush()
    db_session.add(Message(lead_id=lead.id, facebook_campaign_id=hidden_fb_campaign.id))
    db_session.commit()
    response = client.get("/leads/export.csv", headers=world.headers)
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1 and rows[0]["user_id"] == "visible-customer"
    assert rows[0]["account"] == rows[0]["source_campaign"] == ""
    assert "hidden-" not in response.text
