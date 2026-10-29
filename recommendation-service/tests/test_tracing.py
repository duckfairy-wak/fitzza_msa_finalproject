from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
import pytest

from app.core import tracing


def test_tracing_is_off_by_default(monkeypatch):
    monkeypatch.delenv("MANAGEMENT_TRACING_SAMPLING_PROBABILITY", raising=False)

    assert tracing.sampling_probability() == 0.0
    assert tracing.setup_tracing("test-service", FastAPI()) is False


def test_invalid_probability_turns_tracing_off(monkeypatch):
    monkeypatch.setenv("MANAGEMENT_TRACING_SAMPLING_PROBABILITY", "abc")

    assert tracing.sampling_probability() == 0.0


@pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-inf"])
def test_non_finite_probability_turns_tracing_off(monkeypatch, raw):
    monkeypatch.setenv("MANAGEMENT_TRACING_SAMPLING_PROBABILITY", raw)

    assert tracing.sampling_probability() == 0.0
    assert tracing.setup_tracing("test-service") is False


def test_probability_is_clamped(monkeypatch):
    monkeypatch.setenv("MANAGEMENT_TRACING_SAMPLING_PROBABILITY", "5")

    assert tracing.sampling_probability() == 1.0


def test_incoming_traceparent_continues_the_same_trace(monkeypatch):
    """Java(gateway 등)가 보낸 W3C traceparent를 이어받아 같은 trace ID로 기록하는지 확인한다."""
    monkeypatch.setenv("MANAGEMENT_TRACING_SAMPLING_PROBABILITY", "1.0")
    exporter = InMemorySpanExporter()
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    assert tracing.setup_tracing("test-service", app, exporter=exporter) is True

    trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
    response = TestClient(app).get("/ping", headers={"traceparent": f"00-{trace_id}-00f067aa0ba902b7-01"})
    trace.get_tracer_provider().force_flush()

    assert response.status_code == 200
    spans = exporter.get_finished_spans()
    assert spans
    assert {format(span.context.trace_id, "032x") for span in spans} == {trace_id}
