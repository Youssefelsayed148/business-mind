"""Provider-response identities. Never accepts browser account IDs as proof."""
from dataclasses import asdict, dataclass
import json
import re
from typing import Literal

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.meta_authorization import MetaAuthorization
from app.services.meta_compliance import CHANNELS, subject_digest
from app.utils.crypto import encrypt_text

Namespace = Literal["app_user", "business_system_user", "unresolved"]


def provider_id(value: object) -> str:
    if not isinstance(value, (str, int)) or isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,255}", str(value)):
        raise ValueError("invalid provider identity")
    return str(value)


@dataclass(frozen=True)
class MetaGrantIdentity:
    app_id: str
    subject: str
    subject_namespace: Namespace
    platform: Literal["facebook", "whatsapp", "instagram"]
    grant_ids: tuple[str, ...]
    # Only allowlisted IDs, never raw responses containing tokens/profile data.
    provider_context: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.app_id or self.subject_namespace not in ("app_user", "business_system_user", "unresolved"):
            raise ValueError("invalid grant namespace")
        if self.platform not in ("facebook", "whatsapp", "instagram") or not self.grant_ids:
            raise ValueError("invalid channel grants")
        provider_id(self.subject)
        for grant in self.grant_ids:
            provider_id(grant)
        for key, value in self.provider_context:
            if key not in ("waba_id", "phone_id", "profile_id", "user_id", "business_id", "page_id"):
                raise ValueError("unsupported provider context")
            provider_id(value)

    @classmethod
    def facebook(cls, debug: dict, pages: list[dict]) -> "MetaGrantIdentity":
        app_id, subject = cls._debug(debug)
        if debug.get("type") != "USER":
            raise ValueError("user token required")
        grants = tuple(provider_id(page.get("id")) for page in pages)
        if not grants or len(set(grants)) != len(grants):
            raise ValueError("invalid channel grants")
        return cls(app_id, subject, "app_user", "facebook", grants)

    @staticmethod
    def _debug(debug: dict) -> tuple[str, str]:
        if not isinstance(debug, dict) or debug.get("is_valid") is not True or str(debug.get("app_id")) != settings.facebook_app_id:
            raise ValueError("invalid app grant")
        return settings.facebook_app_id, provider_id(debug.get("user_id"))

    @classmethod
    def whatsapp(cls, debug: dict, waba: dict, numbers: list[dict], selected_phone: str) -> "MetaGrantIdentity":
        app_id, subject = cls._debug(debug)
        phone = provider_id(selected_phone)
        grants = tuple(provider_id(number.get("id")) for number in numbers)
        if phone not in grants:
            raise ValueError("phone not in provider WABA grant")
        waba_id = provider_id(waba.get("id"))
        # Even USER/SYSTEM_USER response types do not prove the callback namespace
        # for Embedded Signup. Preserve the subject as unresolved by owner policy.
        return cls(app_id, subject, "unresolved", "whatsapp", grants, (("waba_id", waba_id), ("phone_id", phone)))

    @classmethod
    def instagram(cls, exchange: dict, profile: dict) -> "MetaGrantIdentity":
        if "app_id" in exchange and str(exchange["app_id"]) != settings.META_APP_ID:
            raise ValueError("invalid app grant")
        subject = provider_id(exchange.get("user_id"))
        profile_user = provider_id(profile.get("provider_user_id"))
        if subject != profile_user:
            raise ValueError("exchange/profile grant mismatch")
        # App-bound server code exchange proves this grant's app, but neither
        # profile identifier establishes signed_request.user_id equivalence.
        profile_id = provider_id(profile.get("provider_profile_id"))
        return cls(settings.META_APP_ID, subject, "unresolved", "instagram",
                   (provider_id(profile.get("ig_user_id")),), (("profile_id", profile_id), ("user_id", profile_user)))


def save_grant(db: Session, identity: MetaGrantIdentity, account, grant_id: str) -> None:
    expected_app = settings.META_APP_ID if identity.platform == "instagram" else settings.facebook_app_id
    if identity.app_id != expected_app or grant_id not in identity.grant_ids:
        raise ValueError("app/channel grant mismatch")
    external_key = {"facebook": "page_id", "whatsapp": "phone_number_id", "instagram": "ig_user_id"}[identity.platform]
    if not isinstance(account, CHANNELS[identity.platform][0]) or getattr(account, external_key) != grant_id:
        raise ValueError("account/provider grant mismatch")
    if account.status == "erasure_pending":
        raise ValueError("account erasure pending")
    values = dict(app_id=identity.app_id, subject_digest=subject_digest(identity.app_id, identity.subject),
                  subject_namespace=identity.subject_namespace, subject_encrypted=encrypt_text(identity.subject),
                  provider_context_encrypted=encrypt_text(json.dumps(asdict(identity), separators=(",", ":"))),
                  workspace_id=account.workspace_id, platform=identity.platform, channel_id=account.id,
                  verification_source="oauth_provider_response")
    stmt = insert(MetaAuthorization).values(**values)
    db.execute(stmt.on_conflict_do_update(constraint="uq_meta_authorization_channel",
               set_={key: getattr(stmt.excluded, key) for key in (*values.keys(), "verified_at")
                     if key not in ("platform", "channel_id")}))
