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
