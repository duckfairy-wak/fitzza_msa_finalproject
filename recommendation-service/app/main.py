import asyncio
from contextlib import asynccontextmanager
import logging
import os

from fastapi import APIRouter, FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

from app.api.recommendations import (
    RecommendationApiError,
    internal_router,
    public_router,
)
from app.core.tracing import setup_tracing
from app.schemas.common import HealthResponse


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Warm-up: 서버 기동 시 Fashion-CLIP 모델 및 추천 컴포넌트 사전 적재
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        settings = getattr(app.state, "settings", None)
        if settings is None:
            from app.core.config import get_settings

            settings = get_settings()
            app.state.settings = settings

        if getattr(settings, "enable_lifespan_warmup", True):
            try:
                from app.api.recommendations import _get_coordinator

                logger.info("Fashion-CLIP 모델 및 추천 컴포넌트 사전 적재(Warm-up) 시작...")
                await asyncio.to_thread(_get_coordinator, app)
                logger.info("Fashion-CLIP 모델 및 추천 컴포넌트 사전 적재 완료")
            except Exception as e:
                logger.warning("사전 적재 실패 (지연 로딩으로 폴백): %s", e)
    yield


app = FastAPI(
    title="Fitzza Recommendation Service",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.ready = True
setup_tracing("recommendation-service", app)


def _mount_router_routes(
    target_app: FastAPI,
    router: APIRouter,
    prefix: str = "",
    include_in_schema: bool = True,
) -> None:
    for route in router.routes:
        if isinstance(route, APIRoute):
            target_app.add_api_route(
                path=f"{prefix}{route.path}",
                endpoint=route.endpoint,
                response_model=route.response_model,
                status_code=route.status_code,
                tags=route.tags,
                summary=route.summary,
                methods=list(route.methods or []),
                include_in_schema=include_in_schema,
            )


@app.exception_handler(RecommendationApiError)
async def handle_recommendation_api_error(
    _request: Request,
    exc: RecommendationApiError,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": exc.status_code, "code": exc.code, "message": exc.message},
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _request: Request,
    _exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "status": status.HTTP_400_BAD_REQUEST,
            "code": "INVALID_REQUEST",
            "message": "요청 값이 올바르지 않습니다.",
        },
    )


@app.exception_handler(StarletteHTTPException)
async def handle_http_exception(
    _request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    code = "HTTP_ERROR"
    if exc.status_code == 400:
        code = "BAD_REQUEST"
    elif exc.status_code == 401:
        code = "UNAUTHORIZED"
    elif exc.status_code == 403:
        code = "FORBIDDEN"
    elif exc.status_code == 404:
        code = "NOT_FOUND"
    elif exc.status_code == 405:
        code = "METHOD_NOT_ALLOWED"
    elif exc.status_code == 500:
        code = "INTERNAL_SERVER_ERROR"
    elif exc.status_code == 502:
        code = "BAD_GATEWAY"
    elif exc.status_code == 503:
        code = "SERVICE_UNAVAILABLE"
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": exc.status_code,
            "code": code,
            "message": str(exc.detail) if isinstance(exc.detail, str) else "오류가 발생했습니다.",
        },
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(Exception)
async def handle_unexpected_exception(
    _request: Request,
    exc: Exception,
) -> JSONResponse:
    logging.getLogger(__name__).error("예기치 않은 오류 발생: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "code": "INTERNAL_SERVER_ERROR",
            "message": "서버 내부 오류가 발생했습니다.",
        },
    )


@app.get("/health", response_model=HealthResponse)
def health(request: Request, response: Response) -> HealthResponse:
    ready = getattr(request.app.state, "ready", False)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="UP" if ready else "NOT_READY",
        readiness="UP" if ready else "DOWN",
    )


# 표준 마이크로서비스 경로 (/api/recommendations) -> Swagger 문서 노출
_mount_router_routes(app, public_router, prefix="/api/recommendations", include_in_schema=True)

# 게이트웨이 하위 호환 경로 (/api/v1/recommendations) -> 정상 동작하되 Swagger 중복 방지를 위해 문서에서 숨김
_mount_router_routes(app, public_router, prefix="/api/v1/recommendations", include_in_schema=False)

_mount_router_routes(app, internal_router, include_in_schema=True)
