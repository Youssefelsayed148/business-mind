"""Signed Meta callback intake and a scoped, explicit operator remediation CLI.

No HTTP/Meta/AI calls. OAuth has not yet established callback-subject mappings.
Only provider-verified mappings recorded by an authorized operator are trusted.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
from uuid import UUID

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.data_deletion_request import DataDeletionRequest
from app.models.meta_authorization import MetaAuthorization
from app.models.instagram_account import InstagramAccount
from app.models.facebook_page import FacebookPage
from app.models.whatsapp_account import WhatsappAccount
from app.models.meta_token import MetaToken
from app.models.facebook_token import FacebookToken
from app.models.whatsapp_token import WhatsappToken
from app.models.saas_forward_event import SaasForwardEvent
from app.services.audit_service import write_audit_log

MAX_SIGNED_REQUEST = 16_384
CHANNELS = {
    "instagram": (InstagramAccount, MetaToken, "instagram_account_id"),
    "facebook": (FacebookPage, FacebookToken, "facebook_page_id"),
    "whatsapp": (WhatsappAccount, WhatsappToken, "whatsapp_account_id"),
}


class InvalidSignedRequest(ValueError):
    pass


def _decode(value: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise InvalidSignedRequest()
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        if base64.urlsafe_b64encode(decoded).decode().rstrip("=") != value:
            raise InvalidSignedRequest()
        return decoded
    except ValueError:
        raise InvalidSignedRequest() from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidSignedRequest()
        result[key] = value
    return result


def verify_signed_request(value: str, app_secret: str) -> str:
    """Return the authenticated app-scoped user ID, never a Page/WABA/IG guess."""
    try:
        if not isinstance(value, str) or not 1 <= len(value) <= MAX_SIGNED_REQUEST or not app_secret:
            raise InvalidSignedRequest()
        signature, encoded = value.split(".")
        actual = _decode(signature)
        expected = hmac.new(app_secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
        if len(actual) != 32 or not hmac.compare_digest(actual, expected):
            raise InvalidSignedRequest()
        payload = json.loads(_decode(encoded).decode("utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(payload, dict) or payload.get("algorithm") != "HMAC-SHA256":
            raise InvalidSignedRequest()
        subject = payload.get("user_id")
        if not isinstance(subject, str) or not re.fullmatch(r"[0-9]{1,255}", subject):
            raise InvalidSignedRequest()
        if "issued_at" in payload and (type(payload["issued_at"]) is not int or payload["issued_at"] < 0):
            raise InvalidSignedRequest()
        return subject
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise InvalidSignedRequest() from None


def _digest(value: str) -> str:
    return hmac.new(settings.APP_SECRET_KEY.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def subject_digest(app_id: str, subject: str) -> str:
    return _digest("meta-subject:" + app_id + ":" + subject)


def app_credentials(app: str) -> tuple[str, str]:
    if app == "instagram":
        return settings.META_APP_ID, settings.META_APP_SECRET
    if app == "facebook":
        return settings.facebook_app_id, settings.facebook_app_secret
    raise ValueError("unsupported app namespace")


def record_authorization(db: Session, *, app: str, subject: str, workspace_id: UUID,
                         platform: str, channel_id: UUID, verified_provider_identity: bool) -> None:
    """Operator-only. Caller must verify both app-scoped subject AND channel grant.

    Possession of the business account ID or dashboard access alone is insufficient.
    """
    if not verified_provider_identity or platform not in CHANNELS or not re.fullmatch(r"[0-9]{1,255}", subject):
        raise ValueError("provider identity and channel grant verification required")
    if (app == "instagram") != (platform == "instagram"):
        raise ValueError("app namespace does not match the channel")
    app_id, _ = app_credentials(app)
    model = CHANNELS[platform][0]
    account = db.query(model).filter(model.id == channel_id, model.workspace_id == workspace_id).with_for_update().one_or_none()
    if account is None:
        raise ValueError("channel not found in supplied workspace")
    # The current grant/token belongs to one connecting subject. Replace on re-verification.
    stmt = insert(MetaAuthorization).values(
        app_id=app_id, subject_digest=subject_digest(app_id, subject), workspace_id=workspace_id,
        platform=platform, channel_id=channel_id, verification_source="operator_verified_provider_grant",
    )
    db.execute(stmt.on_conflict_do_update(
        constraint="uq_meta_authorization_channel",
        set_={key: getattr(stmt.excluded, key) for key in
              ("app_id", "subject_digest", "workspace_id", "verification_source", "verified_at")},
    ))
    write_audit_log(db, "meta_authorization_mapping_verified", "Operator verified a Meta authorization mapping",
                    entity_type="meta_authorization", metadata={"platform": platform}, commit=False)
    if db.query(DataDeletionRequest.id).filter(
        DataDeletionRequest.app_id == app_id,
        DataDeletionRequest.subject_digest == subject_digest(app_id, subject),
        DataDeletionRequest.status != "completed",
    ).first():
        _disconnect_known_grants(db, app_id, subject_digest(app_id, subject))


def _disconnect_known_grants(db: Session, app_id: str, digest: str) -> int:
    mappings = db.query(MetaAuthorization).filter(
        MetaAuthorization.app_id == app_id, MetaAuthorization.subject_digest == digest,
    ).all()
    count = 0
    for mapping in mappings:
        if mapping.platform not in CHANNELS:
            continue
        model, token, fk = CHANNELS[mapping.platform]
        account = db.query(model).filter(
            model.id == mapping.channel_id, model.workspace_id == mapping.workspace_id,
        ).with_for_update().one_or_none()
        if account is None:
            continue
        account.status = "disconnected"
        account.saas_delegation_enabled = False
        account.ai_enabled = False
        db.query(token).filter(getattr(token, fk) == account.id).delete(synchronize_session=False)
        # Cancel only ordinary forwards. A16 erasure events must survive delegation off.
        db.query(SaasForwardEvent).filter(
            SaasForwardEvent.platform == mapping.platform, SaasForwardEvent.channel_id == account.id,
            SaasForwardEvent.status == "pending", SaasForwardEvent.event_type != "contact.erasure",
        ).update({"status": "dropped", "payload": {}, "next_attempt_at": None,
                  "completed_at": datetime.now(timezone.utc), "last_error": "authorization_revoked"}, synchronize_session=False)
        count += 1
    return count


def receive_callback(db: Session, *, app: str, kind: str, signed_request: str) -> DataDeletionRequest:
    app_id, app_secret = app_credentials(app)
    subject = verify_signed_request(signed_request, app_secret)
    if kind not in ("deauthorize", "deletion"):
        raise ValueError("unsupported callback kind")
    digest = subject_digest(app_id, subject)
    request_digest = _digest("meta-request:" + app_id + ":" + kind + ":" + signed_request)
    stmt = insert(DataDeletionRequest).values(
        request_digest=request_digest, app_id=app_id, subject_digest=digest, kind=kind,
        confirmation_code=secrets.token_urlsafe(32), status="operator_action",
    ).on_conflict_do_nothing(index_elements=[DataDeletionRequest.request_digest])
    inserted_id = db.execute(stmt.returning(DataDeletionRequest.id)).scalar_one_or_none()
    if inserted_id is not None:
        write_audit_log(db, "meta_compliance_request_received", "Verified Meta callback requires operator follow-up",
                        entity_type="data_deletion_request", entity_id=inserted_id,
                        metadata={"kind": kind}, commit=False)
    row = db.query(DataDeletionRequest).filter(DataDeletionRequest.request_digest == request_digest).one()
    # Pending receipt replay reconciles mappings added by the operator. A completed
    # historical callback must not revoke a newly verified authorization later.
    if row.status != "completed":
        _disconnect_known_grants(db, app_id, digest)
    return row


def complete_request(db: Session, request_id: UUID, *, many_erasure_confirmed: bool,
                     saas_erasure_confirmed: bool) -> None:
    if not many_erasure_confirmed or not saas_erasure_confirmed:
        raise ValueError("both apps require separately verified completion")
    request = db.query(DataDeletionRequest).filter(DataDeletionRequest.id == request_id).with_for_update().one_or_none()
    if request is None:
        raise ValueError("request not found")
    if request.status != "completed":
        request.status = "completed"
        request.completed_at = datetime.now(timezone.utc)
        db.query(MetaAuthorization).filter(MetaAuthorization.app_id == request.app_id,
            MetaAuthorization.subject_digest == request.subject_digest).delete(synchronize_session=False)
        write_audit_log(db, "meta_compliance_request_completed", "Operator confirmed erasure in both applications",
                        entity_type="data_deletion_request", entity_id=request.id, commit=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Authorized local operator workflow; no provider calls; dry-run by default")
    parser.add_argument("action", choices=("map", "complete", "list-pending"))
    parser.add_argument("--database-url-env", default="META_COMPLIANCE_DATABASE_URL")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--app", choices=("instagram", "facebook"))
    parser.add_argument("--platform", choices=tuple(CHANNELS))
    parser.add_argument("--workspace-id", type=UUID)
    parser.add_argument("--channel-id", type=UUID)
    parser.add_argument("--request-id", type=UUID)
    parser.add_argument("--subject-stdin", action="store_true", help="filter pending requests using an independently verified app-scoped subject from stdin")
    parser.add_argument("--verified-provider-identity", action="store_true")
    parser.add_argument("--many-erasure-confirmed", action="store_true")
    parser.add_argument("--saas-erasure-confirmed", action="store_true")
    args = parser.parse_args(argv)
    if args.database_url_env == "DATABASE_URL" or not re.fullmatch(r"[A-Z][A-Z0-9_]*", args.database_url_env):
        print("FAIL: use a dedicated explicit operator database variable")
        return 1
    raw_url = os.environ.get(args.database_url_env)
    if not raw_url:
        print("FAIL: dedicated operator database variable is missing")
        return 1
    engine = None
    try:
        engine = create_engine(raw_url)
        with Session(engine) as db, db.begin():
            if args.action == "map":
                if not all((args.app, args.platform, args.workspace_id, args.channel_id, args.verified_provider_identity)):
                    raise ValueError("verified app, workspace, platform and channel required")
                subject = sys.stdin.readline(MAX_SIGNED_REQUEST).strip()
                record_authorization(db, app=args.app, subject=subject, workspace_id=args.workspace_id,
                                     platform=args.platform, channel_id=args.channel_id,
                                     verified_provider_identity=args.verified_provider_identity)
            elif args.action == "complete":
                complete_request(db, args.request_id, many_erasure_confirmed=args.many_erasure_confirmed,
                                 saas_erasure_confirmed=args.saas_erasure_confirmed)
            else:
                query = db.query(DataDeletionRequest).filter(DataDeletionRequest.status != "completed")
                if args.subject_stdin:
                    if not args.app or not args.verified_provider_identity:
                        raise ValueError("verified app-scoped identity required")
                    app_id, _ = app_credentials(args.app)
                    subject = sys.stdin.readline(MAX_SIGNED_REQUEST).strip()
                    if not re.fullmatch(r"[0-9]{1,255}", subject):
                        raise ValueError("invalid verified identity")
                    query = query.filter(DataDeletionRequest.app_id == app_id,
                                         DataDeletionRequest.subject_digest == subject_digest(app_id, subject))
                pending = query.all()
                for request in pending:
                    print(f"request={request.id} kind={request.kind} status=operator_action")
            if not args.apply:
                db.rollback()
                print("DRY RUN: no changes saved")
            else:
                print("Saved authorized operator action")
        return 0
    except Exception:
        # Database exceptions may contain URLs/identifiers. Never print them.
        print("FAIL: operator action could not be verified or saved")
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
