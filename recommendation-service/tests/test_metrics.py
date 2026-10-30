import socket
import urllib.request

from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, generate_latest
import pytest

from app.core import metrics

SECRET_LOOKING_ID = "987654321"


def make_app(registry, port=None):
    app = FastAPI()

    @app.get("/api/items/{itemId}")
    def item(itemId: int):
        return {"itemId": itemId}

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("secret detail " + SECRET_LOOKING_ID)

    app.add_middleware(
        metrics.PrometheusMiddleware,
        application="test-service",
        histogram=metrics.new_request_histogram(registry),
        port=port,
        registry=registry,
    )
    return app


def samples(registry):
    return [
        sample
        for family in registry.collect()
        if family.name == "http_server_requests_seconds"
        for sample in family.samples
        if sample.name == "http_server_requests_seconds_count"
    ]


def test_requests_are_labelled_by_route_template_not_by_ids_or_query():
    registry = CollectorRegistry()
    client = TestClient(make_app(registry))

    client.get(f"/api/items/{SECRET_LOOKING_ID}?token={SECRET_LOOKING_ID}", headers={"X-User-Id": "123456789"})

    (sample,) = samples(registry)
    assert sample.labels == {
        "application": "test-service",
        "method": "GET",
        "uri": "/api/items/{itemId}",
        "status": "200",
        "outcome": "SUCCESS",
        "exception": "none",
    }
    exposed = generate_latest(registry).decode()
    assert SECRET_LOOKING_ID not in exposed
    assert "123456789" not in exposed
    assert 'http_server_requests_seconds_bucket{' in exposed


def test_unmatched_paths_are_grouped_without_the_raw_path():
    registry = CollectorRegistry()

    TestClient(make_app(registry)).get(f"/api/unknown/{SECRET_LOOKING_ID}")

    (sample,) = samples(registry)
    assert sample.labels["uri"] == "NOT_FOUND"
    assert sample.labels["status"] == "404"
    assert SECRET_LOOKING_ID not in generate_latest(registry).decode()


def test_unhandled_errors_record_500_and_only_the_exception_class():
    registry = CollectorRegistry()

    TestClient(make_app(registry), raise_server_exceptions=False).get("/api/boom")

    (sample,) = samples(registry)
    assert sample.labels["status"] == "500"
    assert sample.labels["outcome"] == "SERVER_ERROR"
    assert sample.labels["exception"] == "RuntimeError"
    assert "secret detail" not in generate_latest(registry).decode()


@pytest.mark.parametrize(("raw", "expected"), [("", 9999), ("9100", 9100), ("0", 0), ("abc", 9999), ("70000", 9999)])
def test_metrics_port_comes_from_management_server_port(monkeypatch, raw, expected):
    monkeypatch.setenv("MANAGEMENT_SERVER_PORT", raw)

    assert metrics.metrics_port(9999) == expected


def test_metrics_are_served_only_on_the_separate_port(monkeypatch):
    monkeypatch.setattr(metrics, "_server_started", False)
    registry = CollectorRegistry()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    with TestClient(make_app(registry, port=port)) as client:
        client.get("/api/items/1")
        assert client.get("/metrics").status_code == 404
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/metrics", timeout=5).read().decode()

    assert "http_server_requests_seconds_count" in body


def test_the_service_app_records_request_metrics():
    from app.main import app

    assert any(m.cls is metrics.PrometheusMiddleware for m in app.user_middleware)
