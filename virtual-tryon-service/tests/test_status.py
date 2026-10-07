from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app, service_status


def test_status() -> None:
    before = datetime.now(timezone.utc)
    with TestClient(app) as client:
        response = client.get("/api/v1/tryon/status")
    after = datetime.now(timezone.utc)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    payload = response.json()
    assert set(payload) == {"service", "status", "timestamp"}
    assert payload["service"] == "virtual-tryon-service"
    assert payload["status"] == "UP"
    timestamp = datetime.fromisoformat(payload["timestamp"])
    assert timestamp.utcoffset() == timedelta(0)
    assert before <= timestamp <= after


def test_status_timestamp_is_generated_for_each_call() -> None:
    for _ in range(2):
        before = datetime.now(timezone.utc)
        payload = service_status()
        after = datetime.now(timezone.utc)

        timestamp = datetime.fromisoformat(payload["timestamp"])
        assert timestamp.utcoffset() == timedelta(0)
        assert before <= timestamp <= after
