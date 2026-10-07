from fastapi.testclient import TestClient

from app.main import app


def test_status() -> None:
    response = TestClient(app).get("/api/v1/recommendations/status")
    assert response.status_code == 200
    assert response.json()["service"] == "recommendation-service"
