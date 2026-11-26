"""Settings builders for the identity credential tests (synthetic keys only)."""

from typing import Any

from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.core.config import Settings
from tests.conftest import build_test_settings

# One throwaway Fernet key per test process; never a real secret.
MFA_KEY = Fernet.generate_key().decode()


def v2_settings(**overrides: Any) -> Settings:
    """Identity flag on, MFA available, the legacy per-IP login limiter out of the way."""
    values: dict[str, Any] = {
        "identity_v2_enabled": True,
        "mfa_secret_encryption_keys": SecretStr(MFA_KEY),
        "login_rate_limit_attempts": 1000,
    }
    values.update(overrides)
    return build_test_settings(**values)
