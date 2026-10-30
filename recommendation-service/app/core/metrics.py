"""Prometheus 애플리케이션 메트릭(FITZZA-314).

Java 서비스(Micrometer)와 같은 이름·라벨을 써서 Grafana에서 한 쿼리로 함께 본다.

- http_server_requests_seconds{application, method, uri, status, outcome, exception}: 요청 수·지연시간 히스토그램
  (p90/p95/p99는 Prometheus에서 histogram_quantile로 계산한다)
- process_*, python_gc_*, python_info: prometheus-client 기본 수집기

uri는 라우트 템플릿(예 /api/v1/recommendations/{requestId})만 쓴다. 매칭되지 않은 경로는 NOT_FOUND/UNKNOWN으로 묶어
ID·쿼리값·원래 URL이 라벨에 들어가지 않게 한다. exception은 예외 클래스 이름만 쓴다(메시지는 넣지 않는다).

메트릭은 일반 API 포트가 아니라 별도 포트(MANAGEMENT_SERVER_PORT)에서만 응답한다. Gateway·Ingress·Service의 http
포트는 이 포트로 라우팅하지 않으므로 클러스터 밖에 노출되지 않는다. 0이면 메트릭 서버를 띄우지 않는다.
Jaeger 추적(app/core/tracing.py)과 독립적으로 동작한다.
"""

import logging
import os
import threading
import time

from prometheus_client import REGISTRY, CollectorRegistry, Histogram, start_http_server

logger = logging.getLogger(__name__)

# Java 서비스 공통 설정(config-service)의 SLO 버킷과 같다.
BUCKETS = (0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf"))
LABELS = ("application", "method", "uri", "status", "outcome", "exception")

_server_lock = threading.Lock()
_server_started = False


def new_request_histogram(registry: CollectorRegistry = REGISTRY) -> Histogram:
    return Histogram(
        "http_server_requests_seconds",
        "HTTP 요청 처리 시간(초)",
        LABELS,
        buckets=BUCKETS,
        registry=registry,
    )


def metrics_port(default: int) -> int:
    raw = os.getenv("MANAGEMENT_SERVER_PORT", "").strip()
    if not raw:
        return default
    try:
        port = int(raw)
    except ValueError:
        logger.warning("MANAGEMENT_SERVER_PORT 값이 숫자가 아니라 기본 포트 %s를 씁니다: %r", default, raw)
        return default
    return port if 0 <= port <= 65535 else default


def _outcome(status_code: int) -> str:
    if status_code < 200:
        return "INFORMATIONAL"
    if status_code < 300:
        return "SUCCESS"
    if status_code < 400:
        return "REDIRECTION"
    if status_code < 500:
        return "CLIENT_ERROR"
    return "SERVER_ERROR"


def _uri(scope: dict, status_code: int) -> str:
    route = scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path
    return "NOT_FOUND" if status_code == 404 else "UNKNOWN"


class PrometheusMiddleware:
    """요청마다 http_server_requests_seconds에 한 번 기록한다. lifespan 시작 때 메트릭 서버를 한 번 띄운다."""

    def __init__(self, app, application: str, histogram: Histogram, port: int | None, registry=REGISTRY):
        self.app = app
        self.application = application
        self.histogram = histogram
        self.port = port
        self.registry = registry

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            self._start_server_once()
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status_code = 500
        exception = "none"
        started = time.perf_counter()

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as error:
            status_code = 500
            exception = type(error).__name__
            raise
        finally:
            self.histogram.labels(
                application=self.application,
                method=scope.get("method", "UNKNOWN"),
                uri=_uri(scope, status_code),
                status=str(status_code),
                outcome=_outcome(status_code),
                exception=exception,
            ).observe(time.perf_counter() - started)

    def _start_server_once(self) -> None:
        global _server_started
        if not self.port:
            return
        with _server_lock:
            if _server_started:
                return
            try:
                start_http_server(self.port, registry=self.registry)
                _server_started = True
                logger.info("Prometheus 메트릭을 포트 %s에서 제공합니다.", self.port)
            except OSError as error:
                # 메트릭 포트를 못 열어도 API 서비스는 계속 뜬다.
                logger.warning("Prometheus 메트릭 포트 %s를 열지 못했습니다: %s", self.port, error)


_histogram: Histogram | None = None


def setup_metrics(app, application: str, default_port: int) -> None:
    """앱에 요청 메트릭 미들웨어를 붙인다. 프로세스당 히스토그램은 하나만 만든다."""
    global _histogram
    if _histogram is None:
        _histogram = new_request_histogram()
    app.add_middleware(
        PrometheusMiddleware,
        application=application,
        histogram=_histogram,
        port=metrics_port(default_port),
    )
