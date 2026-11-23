from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.integrations.meta.whatsapp_ids import normalize_wa_id
from app.models.whatsapp_account import WhatsappAccount
from app.models.whatsapp_consent_event import WhatsappConsentEvent
from app.models.whatsapp_contact import WhatsappContact
from app.services.whatsapp_window_service import in_free_entry_window


@dataclass(frozen=True)
class ImportResult:
    imported: int
    created: int
    deduplicated: int
    invalid: int


class ConsentValidationError(ValueError):
    """Raised when a consent transition lacks its required audit proof."""


MAX_IMPORT_BYTES = 2 * 1024 * 1024
MAX_IMPORT_ROWS = 10_000


def _actor_id(actor: object | None) -> UUID | None:
    value = getattr(actor, "id", actor)
    return value if isinstance(value, UUID) else None


def record_consent_event(
    db: Session,
    contact: WhatsappContact,
    *,
    event_type: str,
    source: str,
    evidence: dict,
    actor: object | None = None,
) -> None:
    db.add(
        WhatsappConsentEvent(
            contact_id=contact.id,
            workspace_id=contact.workspace_id,
            event_type=event_type,
            source=source,
            evidence=evidence,
            actor_user_id=_actor_id(actor),
        )
    )


def grant(
    db: Session,
    *,
    contact: WhatsappContact,
    source: str = "manual",
    actor: object | None = None,
    evidence: dict | None = None,
) -> WhatsappContact:
    actor_id = _actor_id(actor)
    proof = (evidence or {}).get("proof") or (evidence or {}).get("note")
    if source == "manual" and actor_id is None:
        raise ConsentValidationError("manual_consent_actor_required")
    resubscribe = contact.marketing_consent == "opted_out"
    if resubscribe and not evidence:
        raise ConsentValidationError("resubscribe_evidence_required")
    if source == "manual" and (not isinstance(proof, str) or not proof.strip()):
        raise ConsentValidationError("manual_consent_proof_required")
    now = datetime.now(timezone.utc)
    contact.marketing_consent = "opted_in"
    contact.consent_source = source
    contact.consent_at = now
    contact.opted_out_at = None
    record_consent_event(
        db,
        contact,
        event_type="resubscribe" if resubscribe else "opt_in",
        source=source,
        evidence=evidence or {},
        actor=actor,
    )
    db.flush()
    return contact


def apply_keyword_consent(
    db: Session, *, contact: WhatsappContact, keyword: str | None,
    opt_in: set[str], opt_out: set[str], configured_opt_in: bool,
    event_time: datetime, message_id: str | None,
) -> str | None:
    """Apply verified inbound evidence; STOP wins over older/equal opt-ins."""
    if keyword is not None and keyword in opt_out:
        if contact.marketing_consent != "opted_out":
            contact.marketing_consent = "opted_out"
            contact.consent_source = "inbound_keyword"
            contact.opted_out_at = event_time
            record_consent_event(db, contact, event_type="opt_out", source="inbound_keyword",
                                 evidence={"message_id": message_id, "keyword": keyword})
        elif contact.opted_out_at is None or event_time > contact.opted_out_at:
            contact.opted_out_at = event_time
        return "opt_out"
    if (keyword is not None and keyword in opt_in
            and (configured_opt_in or contact.marketing_consent == "opted_out")):
        opted_out_at = contact.opted_out_at
        if opted_out_at is not None:
            if opted_out_at.tzinfo is None:
                opted_out_at = opted_out_at.replace(tzinfo=timezone.utc)
            if event_time <= opted_out_at:
                return None
        if contact.marketing_consent != "opted_in":
            contact.marketing_consent = "opted_in"
            contact.consent_source = "inbound_keyword"
            contact.consent_at = event_time
            contact.opted_out_at = None
            record_consent_event(db, contact, event_type="opt_in", source="inbound_keyword",
                                 evidence={"message_id": message_id, "keyword": keyword})
        return "opt_in"
    return None


def revoke(
    db: Session,
    *,
    contact: WhatsappContact,
    source: str = "manual",
    actor: object | None = None,
    evidence: dict | None = None,
) -> WhatsappContact:
    contact.marketing_consent = "opted_out"
    contact.consent_source = source
    contact.opted_out_at = datetime.now(timezone.utc)
    record_consent_event(db, contact, event_type="revoke", source=source, evidence=evidence or {}, actor=actor)
    db.flush()
    return contact


def is_marketing_allowed(
    contact: WhatsappContact,
    account: WhatsappAccount,
    *,
    now: datetime | None = None,
) -> bool:
    if contact.marketing_consent == "opted_out":
        return False
    return contact.marketing_consent == "opted_in" or (
        account.ctwa_counts_as_consent and in_free_entry_window(contact, now=now)
    )


def import_contacts(
    db: Session,
    *,
    account: WhatsappAccount,
    csv_data: str | bytes,
    filename: str,
    actor: object | None,
    attestation_text: str | None = None,
) -> ImportResult:
    raw = csv_data if isinstance(csv_data, bytes) else csv_data.encode("utf-8")
    if len(raw) > MAX_IMPORT_BYTES:
        raise ConsentValidationError("import_file_too_large")
    if not isinstance(attestation_text, str) or not attestation_text.strip():
        raise ConsentValidationError("import_attestation_required")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ConsentValidationError("import_csv_must_be_utf8") from exc
    file_hash = hashlib.sha256(raw).hexdigest()
    rows = csv.DictReader(io.StringIO(text))
    created = deduplicated = invalid = imported = 0
    for row_number, row in enumerate(rows, start=2):
        if row_number > MAX_IMPORT_ROWS + 1:
            raise ConsentValidationError("import_row_limit_exceeded")
        raw_id = row.get("wa_id") or row.get("phone") or row.get("phone_number") or ""
        raw_id = str(raw_id).strip()
        wa_id = normalize_wa_id(raw_id)
        # Imports must declare an international number explicitly. Formatting
        # and local-looking numbers are rejected instead of guessed.
        if wa_id is None or not raw_id.startswith("+") or raw_id[1:] != wa_id:
            invalid += 1
            continue
        contact = (
            db.query(WhatsappContact)
            .filter(
                WhatsappContact.whatsapp_account_id == account.id,
                WhatsappContact.wa_id == wa_id,
            )
            .first()
        )
        created_contact = contact is None
        if created_contact:
            contact = WhatsappContact(
                workspace_id=account.workspace_id,
                whatsapp_account_id=account.id,
                wa_id=wa_id,
                display_name=row.get("display_name") or row.get("name") or None,
                marketing_consent="unknown",
            )
            db.add(contact)
            db.flush()
            created += 1
        else:
            deduplicated += 1

        attested = True
        # An import can grant unknown contacts, but can never undo an opt-out.
        skipped_opted_out = attested and contact.marketing_consent == "opted_out"
        if attested and contact.marketing_consent == "unknown":
            contact.marketing_consent = "opted_in"
            contact.consent_source = "imported_attested"
            contact.consent_at = datetime.now(timezone.utc)
        # Unattested imports never modify an existing consent decision. New
        # contacts already start at unknown above.

        record_consent_event(
            db,
            contact,
            event_type="import",
            source="imported_attested" if attested else "manual",
            actor=actor,
            evidence={
                "filename": filename,
                "file_hash": file_hash,
                "uploader": str(_actor_id(actor)) if _actor_id(actor) else None,
                "attestation_text": attestation_text or "",
                "row_number": row_number,
                "skipped_opted_out": skipped_opted_out,
            },
        )
        imported += 1
    db.flush()
    return ImportResult(imported, created, deduplicated, invalid)
