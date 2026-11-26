"""verify_assertion: signature, claims, replay and fail-closed behavior. Synthetic keys made per run."""
import base64
import hashlib
import hmac
import json
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key as rsa_key
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.config import settings
from app.services.sso_assertion import (
    CLOCK_SKEW_SECONDS,
    JTI_TTL_SECONDS,
    MAX_LIFETIME_SECONDS,
    SSOAssertionError,
    verify_assertion,
)

KID = "k1"
PRIVATE = Ed25519PrivateKey.generate()


def _pem(private) -> str:
    return private.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()


class FakeRedis:
    def __init__(self):
        self.seen = set()

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.seen:
            return None
        self.seen.add(key)
        return True


class DownRedis:
    def set(self, *a, **k):
        raise RedisConnectionError("down")


@pytest.fixture(autouse=True)
def sso_settings(monkeypatch):
    monkeypatch.setattr(settings, "SSO_ASSERTION_ENABLED", True)
    monkeypatch.setattr(settings, "SSO_PUBLIC_KEYS", json.dumps({KID: _pem(PRIVATE)}))
    monkeypatch.setattr(settings, "SSO_REQUIRE_MFA_FOR_ADMIN", False)


def claims(**over):
    now = int(time.time())
    base = {
        "iss": settings.SSO_ISSUER, "aud": settings.SSO_AUDIENCE, "sub": str(uuid.uuid4()),
        "jti": uuid.uuid4().hex, "iat": now, "nbf": now, "exp": now + 60,
        "email": "Person@Example.TEST", "scope": "client", "org": str(uuid.uuid4()),
        "workspace": str(uuid.uuid4()), "role": "admin", "locations": None, "via_agency": None, "mfa": True,
    }
    base.update(over)
    return {k: v for k, v in base.items() if v is not ...}


def mint(over=None, key=PRIVATE, kid=KID):
    return jwt.encode(claims(**(over or {})), key, algorithm="EdDSA", headers={"kid": kid} if kid else None)


def reason(token, redis_client=None):
    with pytest.raises(SSOAssertionError) as exc:
        verify_assertion(token, redis_client or FakeRedis())
    return exc.value.reason


def test_valid_client_assertion():
    a = verify_assertion(mint(), FakeRedis())
    assert a.scope == "client" and a.role == "admin" and a.email == "person@example.test"
    assert a.org and a.workspace and a.mfa is True


def test_valid_staff_assertion_has_no_org():
    a = verify_assertion(mint({"scope": "staff", "org": ..., "workspace": ..., "role": ...}), FakeRedis())
    assert a.scope == "staff" and a.org is None and a.workspace is None


def test_staff_assertion_may_name_one_organization_and_workspace():
    org, ws = str(uuid.uuid4()), str(uuid.uuid4())
    a = verify_assertion(mint({"scope": "staff", "org": org, "workspace": ws, "role": ...}), FakeRedis())
    assert a.scope == "staff" and str(a.org) == org and str(a.workspace) == ws and a.role is None


def test_staff_assertion_naming_only_half_a_pair_is_refused():
    half = {"scope": "staff", "role": ...}
    assert reason(mint({**half, "org": str(uuid.uuid4()), "workspace": ...})) == "bad_workspace"
    assert reason(mint({**half, "org": ..., "workspace": str(uuid.uuid4())})) == "bad_org"
    assert reason(mint({**half, "org": "not-a-uuid", "workspace": str(uuid.uuid4())})) == "bad_org"


def test_expired():
    now = int(time.time())
    assert reason(mint({"iat": now - 200, "nbf": now - 200, "exp": now - 100})) == "expired"


def test_not_yet_valid_beyond_skew():
    now = int(time.time())
    assert reason(mint({"iat": now, "nbf": now + 120, "exp": now + 150})) == "not_yet_valid"


def test_skew_boundaries_accepted():
    now = int(time.time())
    verify_assertion(mint({"nbf": now + 20}), FakeRedis())  # inside the 30 s skew
    verify_assertion(mint({"iat": now - 70, "nbf": now - 70, "exp": now - 10}), FakeRedis())  # expired 10 s ago


def test_lifetime_over_60_seconds_rejected():
    now = int(time.time())
    assert reason(mint({"exp": now + 300})) == "lifetime_too_long"


def test_wrong_audience_and_issuer():
    assert reason(mint({"aud": "saas-api"})) == "bad_aud"
    assert reason(mint({"iss": "someone-else"})) == "bad_iss"


def test_unknown_or_missing_kid():
    assert reason(mint(kid="nope")) == "unknown_kid"
    assert reason(mint(kid=None)) == "missing_kid"


def test_signed_by_a_different_key():
    assert reason(mint(key=Ed25519PrivateKey.generate())) == "bad_signature"


def test_tampered_payload():
    head, body, sig = mint().split(".")
    forged = json.loads(base64.urlsafe_b64decode(body + "=="))
    forged["role"] = "owner"
    body2 = base64.urlsafe_b64encode(json.dumps(forged).encode()).rstrip(b"=").decode()
    assert reason(f"{head}.{body2}.{sig}") == "bad_signature"


def test_alg_none_rejected():
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    token = f"{b64({'alg': 'none', 'kid': KID, 'typ': 'JWT'})}.{b64(claims())}."
    assert reason(token) == "bad_alg"


def test_hs256_signed_with_public_key_pem_rejected():
    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    signing_input = f"{b64({'alg': 'HS256', 'kid': KID, 'typ': 'JWT'})}.{b64(claims())}"
    mac = hmac.new(_pem(PRIVATE).encode(), signing_input.encode(), hashlib.sha256).digest()
    token = signing_input + "." + base64.urlsafe_b64encode(mac).rstrip(b"=").decode()
    assert reason(token) == "bad_alg"


def test_non_ed25519_key_configured(monkeypatch):
    rsa = rsa_key(public_exponent=65537, key_size=2048)
    pem = rsa.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
    monkeypatch.setattr(settings, "SSO_PUBLIC_KEYS", json.dumps({KID: pem}))
    assert reason(mint()) == "key_not_ed25519"


def test_garbage_token():
    assert reason("not-a-jwt") == "malformed"


def test_replay_is_rejected():
    store = FakeRedis()
    token = mint()
    verify_assertion(token, store)
    assert reason(token, store) == "replay"


def test_invalid_assertion_does_not_consume_jti():
    store = FakeRedis()
    jti = uuid.uuid4().hex
    assert reason(mint({"jti": jti, "aud": "wrong"}), store) == "bad_aud"
    assert store.seen == set()
    verify_assertion(mint({"jti": jti}), store)


def test_redis_down_fails_closed():
    assert reason(mint(), DownRedis()) == "replay_store_unavailable"


@pytest.mark.parametrize(
    "over,expected",
    [
        ({"scope": "root"}, "bad_scope"),
        ({"role": "superuser"}, "bad_role"),
        ({"org": "not-a-uuid"}, "bad_org"),
        ({"workspace": ...}, "bad_workspace"),
        ({"sub": "nope"}, "bad_sub"),
        ({"mfa": "yes"}, "bad_mfa"),
        ({"jti": "short"}, "bad_jti"),
        ({"jti": ...}, "missing_claim"),
        ({"locations": ["loc-1"]}, "limited_scope_unsupported"),
    ],
)
def test_claim_validation(over, expected):
    assert reason(mint(over)) == expected


def test_mfa_requirement_only_when_flag_on(monkeypatch):
    verify_assertion(mint({"mfa": False, "role": "owner"}), FakeRedis())  # flag off: fine
    monkeypatch.setattr(settings, "SSO_REQUIRE_MFA_FOR_ADMIN", True)
    assert reason(mint({"mfa": False, "role": "admin"})) == "mfa_required"
    assert reason(mint({"mfa": False, "scope": "staff", "org": ..., "workspace": ..., "role": ...})) == "mfa_required"
    verify_assertion(mint({"mfa": False, "role": "agent"}), FakeRedis())  # not an admin role
    verify_assertion(mint({"mfa": True, "role": "owner"}), FakeRedis())


def test_malformed_key_config(monkeypatch):
    monkeypatch.setattr(settings, "SSO_PUBLIC_KEYS", "not json")
    assert reason(mint()) == "keys_misconfigured"


def test_jti_ttl_outlives_the_widest_verifiable_window():
    assert JTI_TTL_SECONDS >= MAX_LIFETIME_SECONDS + 2 * CLOCK_SKEW_SECONDS + 30
