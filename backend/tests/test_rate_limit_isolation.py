from uuid import uuid4

import pytest

from app.core.config import settings
from app.services import rate_limit_service


def test_ordinary_tests_do_not_touch_shared_rate_limit_counters(monkeypatch):
    def unexpected_redis_access():
        pytest.fail("ordinary tests must not consume shared Redis rate-limit counters")

    monkeypatch.setattr(rate_limit_service, "_redis", unexpected_redis_access)
    assert settings.RATE_LIMIT_ENABLED is False
    assert rate_limit_service.rate_limit("unused-test-key", 1, 60).allowed


@pytest.mark.rate_limit
def test_opt_in_marker_enforces_the_real_redis_limit():
    assert settings.RATE_LIMIT_ENABLED is True
    client = rate_limit_service._redis()
    key = rate_limit_service.rate_limit_key("t0-isolation", str(uuid4()))
    try:
        first = rate_limit_service.rate_limit(key, 1, 60)
        second = rate_limit_service.rate_limit(key, 1, 60)
        assert first.allowed is True
        assert second.allowed is False
        assert second.retry_after > 0
        assert client.get(key) == "2"
    finally:
        client.delete(key)
