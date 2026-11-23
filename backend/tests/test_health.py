from fastapi.testclient import TestClient

from tests.conftest import skip_if_no_db


@skip_if_no_db
def test_health_returns_200_and_ok(client: TestClient, monkeypatch):
    monkeypatch.setattr("app.api.routes_health.check_redis", lambda: True)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert data["redis"] == "ok"
    assert "service" in data
    assert "environment" in data
