from fastapi import APIRouter, FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from app.api.recommendations import (
    RecommendationApiError,
    internal_router,
    public_router,
)
from app.schemas.common import HealthResponse

app = FastAPI(title="Fitzza Recommendation Service", version="0.1.0")
app.state.ready = True


def _mount_router_routes(
    target_app: FastAPI,
    router: APIRouter,
    prefix: str = "",
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
            )


@app.exception_handler(RecommendationApiError)
async def handle_recommendation_api_error(
    _request: Request,
    exc: RecommendationApiError,
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(
    _request: Request,
    _exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"code": "INVALID_REQUEST", "message": "요청 값이 올바르지 않습니다."},
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


_mount_router_routes(app, public_router, prefix="/api/v1/recommendations")
_mount_router_routes(app, internal_router)
