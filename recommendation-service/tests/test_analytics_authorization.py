from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.clients.user_client import UserServiceClient, UserServiceUnavailableError
from app.core.config import Settings
from app.main import app


@pytest.mark.parametrize("profile", [{"role": "USER"}, {}, {"role": "admin"}, {"role": None}])
def test_non_admin_profile_cannot_aggregate(monkeypatch, profile):
    lookup = Mock(return_value=profile)
    aggregate = Mock()
    monkeypatch.setattr(app.state, "user_client", SimpleNamespace(get_user_profile=lookup), raising=False)
    monkeypatch.setattr(app.state, "repository", SimpleNamespace(get_analytics_data=aggregate), raising=False)
    response = TestClient(app).get(
        "/api/recommendations/analytics",
        headers={"X-User-Id": "4", "X-User-Role": "ADMIN", "X-Admin-Token": "obsolete"},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    aggregate.assert_not_called()


def test_profile_service_failure_denies_access(monkeypatch):
    lookup = Mock(side_effect=UserServiceUnavailableError())
    aggregate = Mock()
    monkeypatch.setattr(app.state, "user_client", SimpleNamespace(get_user_profile=lookup), raising=False)
    monkeypatch.setattr(app.state, "repository", SimpleNamespace(get_analytics_data=aggregate), raising=False)
    response = TestClient(app).get("/api/v1/recommendations/analytics", headers={"X-User-Id": "7"})
    assert response.status_code == 503
    assert response.json()["code"] == "AUTH_UNAVAILABLE"
    aggregate.assert_not_called()


def test_missing_user_does_not_call_profile_service(monkeypatch):
    lookup = Mock()
    monkeypatch.setattr(app.state, "user_client", SimpleNamespace(get_user_profile=lookup), raising=False)
    response = TestClient(app).get("/api/recommendations/analytics", headers={"X-Admin-Token": "obsolete"})
    assert response.status_code == 401
    lookup.assert_not_called()


@pytest.mark.parametrize("status_code, payload, unavailable", [
    (200, {"role": "ADMIN"}, False),
    (200, {"role": "USER"}, False),
    (401, {}, False),
    (403, {}, False),
    (404, {}, False),
    (500, {}, True),
    (200, [], True),
])
def test_profile_client_contract(monkeypatch, status_code, payload, unavailable):
    def handler(request):
        assert str(request.url) == "http://user-service:8081/api/users/me"
        assert request.headers["X-User-Id"] == "7"
        assert request.headers["X-Request-Id"] == "analytics-test"
        return httpx.Response(status_code, json=payload)

    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs
    ))
    client = UserServiceClient(Settings(user_service_url="http://user-service:8081/"))
    if unavailable:
        with pytest.raises(UserServiceUnavailableError):
            client.get_user_profile(7, request_id_header="analytics-test")
    else:
        assert client.get_user_profile(7, request_id_header="analytics-test") == payload


def test_profile_client_timeout(monkeypatch):
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs
    ))
    with pytest.raises(UserServiceUnavailableError):
        UserServiceClient(Settings(user_service_url="http://user-service:8081")).get_user_profile(7)
