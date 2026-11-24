import pytest

from app.core.config import Settings, validate_sso_settings


def _cfg(**kw):
    return Settings(META_APP_SECRET="x", META_WEBHOOK_VERIFY_TOKEN="x", DATABASE_URL="postgresql://x/y", JWT_SECRET="x", **kw)


def test_defaults_are_off():
    cfg = _cfg()
    assert cfg.SSO_ASSERTION_ENABLED is False
    assert cfg.SSO_PUBLIC_KEYS == ""
    assert cfg.SSO_REQUIRE_MFA_FOR_ADMIN is False
    assert (cfg.SSO_ISSUER, cfg.SSO_AUDIENCE, cfg.SSO_TOKEN_MINUTES) == ("business-mind-saas", "many-api", 10)
    validate_sso_settings(cfg)  # off: never raises, even with no keys


@pytest.mark.parametrize(
    "keys",
    ["", "not json", "[]", "{}", '{"k": ""}', '{"": "pem"}', '{"k": 1}'],
)
def test_enabled_with_bad_keys_fails(keys):
    with pytest.raises(RuntimeError):
        validate_sso_settings(_cfg(SSO_ASSERTION_ENABLED=True, SSO_PUBLIC_KEYS=keys))


@pytest.mark.parametrize("minutes", [0, 61])
def test_enabled_with_bad_lifetime_fails(minutes):
    with pytest.raises(RuntimeError):
        validate_sso_settings(
            _cfg(SSO_ASSERTION_ENABLED=True, SSO_PUBLIC_KEYS='{"k1": "pem"}', SSO_TOKEN_MINUTES=minutes)
        )


def test_enabled_with_valid_values_passes():
    validate_sso_settings(_cfg(SSO_ASSERTION_ENABLED=True, SSO_PUBLIC_KEYS='{"k1": "pem"}'))
