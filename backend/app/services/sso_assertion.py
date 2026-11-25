"""Verification of the SaaS-signed SSO assertion (identity design 2.2 to 2.4).

An assertion is a short-lived EdDSA JWT minted by the SaaS. Many holds public
keys only (settings.SSO_PUBLIC_KEYS, a JSON map kid -> PEM) and therefore can
never mint one. verify_assertion() checks, in this order: header (alg and kid),
signature, registered claims, our own claims, then consumes the single-use jti.
Any failure raises SSOAssertionError; the caller answers with one generic
message and records the machine-readable reason in the audit log only.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings

ALGORITHM = "EdDSA"
MAX_LIFETIME_SECONDS = 60
CLOCK_SKEW_SECONDS = 30
# The widest verifiable window is skew + lifetime + skew (30 + 60 + 30 = 120 s).
# The TTL adds a 30 s margin so a jti is never forgotten while its assertion
# could still verify, whatever the Redis expiry rounding or clock drift.
JTI_TTL_SECONDS = 150
SCOPES = {"staff", "client"}
ORG_ROLES = {"owner", "admin", "manager", "agent", "viewer"}
ADMIN_ROLES = {"owner", "admin"}


class SSOAssertionError(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Assertion:
    sub: uuid.UUID
    jti: str
    scope: str
    email: str | None
    mfa: bool
    org: uuid.UUID | None = None
    workspace: uuid.UUID | None = None
    role: str | None = None
    via_agency: str | None = None


_redis_client: Redis | None = None


def _redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


def _public_keys() -> dict[str, str]:
    try:
        keys = json.loads(settings.SSO_PUBLIC_KEYS or "{}")
    except ValueError:
        raise SSOAssertionError("keys_misconfigured")
    if not isinstance(keys, dict):
        raise SSOAssertionError("keys_misconfigured")
    return keys


def _key_for(kid: str) -> Ed25519PublicKey:
    pem = _public_keys().get(kid)
    if not isinstance(pem, str):
        raise SSOAssertionError("unknown_kid")
    try:
        key = load_pem_public_key(pem.encode())
    except Exception:
        raise SSOAssertionError("key_unreadable")
    if not isinstance(key, Ed25519PublicKey):
        raise SSOAssertionError("key_not_ed25519")
    return key


def _uuid(value: object, reason: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise SSOAssertionError(reason)


def verify_assertion(token: str, redis_client: Redis | None = None) -> Assertion:
    # 1. Header: pin the algorithm before any key is touched (blocks "none" and
    #    HS256-with-the-public-key-as-secret), and require a known kid.
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError:
        raise SSOAssertionError("malformed")
    if header.get("alg") != ALGORITHM:
        raise SSOAssertionError("bad_alg")
    kid = header.get("kid")
    if not isinstance(kid, str) or not kid:
        raise SSOAssertionError("missing_kid")
    key = _key_for(kid)

    # 2. Signature and registered claims.
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=[ALGORITHM],
            audience=settings.SSO_AUDIENCE,
            issuer=settings.SSO_ISSUER,
            leeway=CLOCK_SKEW_SECONDS,
            options={"require": ["exp", "nbf", "iat", "iss", "aud", "sub", "jti"]},
        )
    except jwt.ExpiredSignatureError:
        raise SSOAssertionError("expired")
    except jwt.ImmatureSignatureError:
        raise SSOAssertionError("not_yet_valid")
    except jwt.InvalidAudienceError:
        raise SSOAssertionError("bad_aud")
    except jwt.InvalidIssuerError:
        raise SSOAssertionError("bad_iss")
    except jwt.MissingRequiredClaimError:
        raise SSOAssertionError("missing_claim")
    except jwt.PyJWTError:
        raise SSOAssertionError("bad_signature")

    # 3. Our own rules.
    if claims["exp"] - claims["iat"] > MAX_LIFETIME_SECONDS:
        raise SSOAssertionError("lifetime_too_long")
    scope = claims.get("scope")
    if scope not in SCOPES:
        raise SSOAssertionError("bad_scope")
    jti = claims["jti"]
    if not isinstance(jti, str) or not 16 <= len(jti) <= 64:
        raise SSOAssertionError("bad_jti")
    mfa = claims.get("mfa")
    if not isinstance(mfa, bool):
        raise SSOAssertionError("bad_mfa")
    email = claims.get("email")
    if email is not None and not isinstance(email, str):
        raise SSOAssertionError("bad_email")
    sub = _uuid(claims["sub"], "bad_sub")

    org = workspace = role = via_agency = None
    if scope == "client":
        org = _uuid(claims.get("org"), "bad_org")
        workspace = _uuid(claims.get("workspace"), "bad_workspace")
        role = claims.get("role")
        if role not in ORG_ROLES:
            raise SSOAssertionError("bad_role")
        # Location-limited members get no Many access in this phase (design 4.2).
        if claims.get("locations") is not None:
            raise SSOAssertionError("limited_scope_unsupported")
        agency = claims.get("via_agency")
        if agency is not None and not isinstance(agency, str):
            raise SSOAssertionError("bad_via_agency")
        via_agency = agency
    if settings.SSO_REQUIRE_MFA_FOR_ADMIN and not mfa and (scope == "staff" or role in ADMIN_ROLES):
        raise SSOAssertionError("mfa_required")

    # 4. Single use. Last on purpose: only a fully valid assertion consumes a
    #    jti. Fail closed: no Redis, no exchange.
    try:
        first_use = (redis_client or _redis()).set(f"sso:jti:{jti}", "1", nx=True, ex=JTI_TTL_SECONDS)
    except RedisError:
        raise SSOAssertionError("replay_store_unavailable")
    if not first_use:
        raise SSOAssertionError("replay")

    return Assertion(
        sub=sub, jti=jti, scope=scope, email=email.lower() if email else None, mfa=mfa,
        org=org, workspace=workspace, role=role, via_agency=via_agency,
    )
