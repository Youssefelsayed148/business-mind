from fastapi.testclient import TestClient

from app.api import routes_health
from app.core.config import get_allowed_origins, settings
from app.db.session import get_db
from app.main import app


def _override_db():
    yield object()


def test_health_fails_if_database_unavailable_mocked(monkeypatch):
    monkeypatch.setattr(routes_health, "check_database", lambda db: (_ for _ in ()).throw(Exception("db down")))
    monkeypatch.setattr(routes_health, "check_redis", lambda: True)
    app.dependency_overrides[get_db] = _override_db
    try:
        response = TestClient(app).get("/health")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json()["database"] == "error"
    assert response.json()["redis"] == "ok"


def test_health_fails_if_redis_unavailable_mocked(monkeypatch):
    monkeypatch.setattr(routes_health, "check_database", lambda db: True)
    monkeypatch.setattr(routes_health, "check_redis", lambda: False)
    app.dependency_overrides[get_db] = _override_db
    try:
        response = TestClient(app).get("/health")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json()["database"] == "ok"
    assert response.json()["redis"] == "error"


def test_production_cors_uses_allowed_origins(monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_ORIGINS", "https://automation.example.com,https://admin.example.com")

    assert get_allowed_origins() == [
        "https://automation.example.com",
        "https://admin.example.com",
    ]


def test_webhook_signature_required_in_production(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")

    response = TestClient(app).post("/webhooks/meta", content=b"{}")

    assert response.status_code == 403
