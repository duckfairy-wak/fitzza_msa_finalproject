"""분산 트레이싱(Jaeger) 설정.

Java 서비스(#203)와 같은 환경변수와 W3C traceparent 헤더를 써서, Java → FastAPI → 다른 서비스 호출이
Jaeger에서 하나의 trace로 이어지게 한다.

- MANAGEMENT_TRACING_SAMPLING_PROBABILITY: 0(기본)이면 아무것도 하지 않는다. 로컬 Compose는 1.0으로 켠다.
- MANAGEMENT_OTLP_TRACING_ENDPOINT: OTLP HTTP 주소(기본 http://localhost:4318/v1/traces, Compose는 http://jaeger:4318/v1/traces).
"""

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "http://localhost:4318/v1/traces"
_provider_configured = False


def sampling_probability() -> float:
    raw = os.getenv("MANAGEMENT_TRACING_SAMPLING_PROBABILITY", "0").strip()
    try:
        value = float(raw)
    except ValueError:
        logger.warning("MANAGEMENT_TRACING_SAMPLING_PROBABILITY 값이 숫자가 아니라 추적을 끕니다: %r", raw)
        return 0.0
    return min(max(value, 0.0), 1.0)


def setup_tracing(service_name: str, app=None, exporter=None) -> bool:
    """추적을 켜면 True. app을 주면 FastAPI 요청도 계측한다(health는 제외).

    exporter는 테스트에서 메모리 수집기를 넣을 때만 쓴다.
    """
    global _provider_configured
    probability = sampling_probability()
    if probability <= 0.0:
        return False

    if not _provider_configured:
        from opentelemetry import trace
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        if exporter is None:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=os.getenv("MANAGEMENT_OTLP_TRACING_ENDPOINT", DEFAULT_ENDPOINT))

        # 앞 서비스가 보낸 traceparent의 샘플링 결정을 따르고, 처음 시작하는 요청만 비율로 고른다(Java와 같은 방식).
        provider = TracerProvider(
            resource=Resource.create({"service.name": service_name}),
            sampler=ParentBased(TraceIdRatioBased(probability)),
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        # 이미 만들어 둔 httpx 클라이언트의 호출에도 traceparent를 실어 보낸다.
        HTTPXClientInstrumentor().instrument()
        _provider_configured = True
        logger.info("분산 트레이싱 켜짐: service=%s, sampling=%s", service_name, probability)

    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    return True
