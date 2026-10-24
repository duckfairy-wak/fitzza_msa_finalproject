"""Fitzza 가상 피팅(VTON) 서비스 메인 애플리케이션."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

import logging
import os
from starlette.concurrency import run_in_threadpool
from PIL import Image

from fastapi.routing import APIRoute

from app.api.vton import router as vton_router
from app.core.tracing import setup_tracing
from app.services.vton_generator import (
    DEFAULT_MODEL,
    SUPPORTED_CATEGORIES,
    VtonConfigurationError,
    VtonError,
    VtonUpstreamError,
    VtonValidationError,
    generate_tryon_image,
)

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 파일당 최대 15MB


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
                description=route.description,
                methods=list(route.methods or []),
                responses=route.responses,
                response_class=route.response_class,
                openapi_extra=route.openapi_extra,
            )


app = FastAPI(
    title="Fitzza Virtual Try-On Service",
    description="Fitzza AI 가상 피팅 서비스 (OpenAI 기반 다중 의류 가상 착용)",
    version="0.2.0",
)
app.state.ready = True
_mount_router_routes(app, vton_router)
setup_tracing("vton-service", app)



def custom_openapi():
    """Swagger UI에서 다중 이미지 파일을 업로드할 수 있도록 바이너리 포맷 스키마를 설정합니다."""
    if app.openapi_schema:
        return app.openapi_schema

    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

    components = schema.get("components", {}).get("schemas", {})
    for component in components.values():
        properties = component.get("properties", {})
        for prop in properties.values():
            if prop.get("type") == "array":
                items = prop.get("items", {})
                if items.get("contentMediaType") == "application/octet-stream":
                    items.pop("contentMediaType", None)
                    items["format"] = "binary"
            elif prop.get("contentMediaType") == "application/octet-stream":
                prop.pop("contentMediaType", None)
                prop["format"] = "binary"

    app.openapi_schema = schema
    return app.openapi_schema


app.openapi = custom_openapi


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


@app.exception_handler(VtonValidationError)
async def handle_vton_validation_error(
    _request: Request,
    exc: VtonValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "status": status.HTTP_400_BAD_REQUEST,
            "code": "INVALID_REQUEST",
            "message": str(exc),
        },
    )


@app.exception_handler(VtonConfigurationError)
async def handle_vton_config_error(
    _request: Request,
    exc: VtonConfigurationError,
) -> JSONResponse:
    logger.error("VTON 서버 설정 오류: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "code": "CONFIGURATION_ERROR",
            "message": "가상 피팅 서비스 환경 설정 오류가 발생했습니다. 관리자에게 문의하세요.",
        },
    )


@app.exception_handler(VtonUpstreamError)
async def handle_vton_upstream_error(
    _request: Request,
    exc: VtonUpstreamError,
) -> JSONResponse:
    logger.error("VTON OpenAI API 호출 오류: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={
            "status": status.HTTP_502_BAD_GATEWAY,
            "code": "UPSTREAM_ERROR",
            "message": "AI 이미지 생성 서버와의 통신에 실패했습니다.",
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
    logger.error("VTON 예기치 않은 오류 발생: %s", exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "code": "INTERNAL_SERVER_ERROR",
            "message": "가상 피팅 처리 중 일시적인 오류가 발생했습니다.",
        },
    )


class HealthResponse(BaseModel):
    status: Literal["UP", "NOT_READY"]
    liveness: Literal["UP"] = "UP"
    readiness: Literal["UP", "DOWN"]


@app.get("/health", response_model=HealthResponse)
def health(request: Request, response: Response) -> HealthResponse:
    ready = getattr(request.app.state, "ready", False)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="UP" if ready else "NOT_READY",
        readiness="UP" if ready else "DOWN",
    )


@app.post(
    "/api/vton/clothing-transfer",
    response_class=Response,
    summary="[Swagger 테스트용] 실시간 다중 의류 가상 피팅",
    description=(
        "기본 아바타 인물에 사용자가 직접 첨부한 의류 이미지들을 실시간으로 합성하여 "
        "완성된 PNG 이미지를 즉시 반환합니다."
    ),
    responses={
        200: {
            "content": {"image/png": {}},
            "description": "가상 피팅 완료 PNG 이미지",
        },
        400: {"description": "입력 카테고리 또는 이미지 유효성 오류"},
        500: {"description": "기본 아바타 또는 서버 설정 오류"},
        502: {"description": "OpenAI 이미지 생성 API 호출 실패"},
    },
)
async def clothing_transfer(
    categories_json: Annotated[
        str,
        Form(
            description=(
                '착용할 카테고리 목록. JSON 배열(예: ["상의", "하의"]) '
                '또는 쉼표 구분 문자열(예: 상의,하의). '
                '허용 카테고리: 상의, 하의, 아우터, 신발, 모자'
            )
        ),
    ],
    clothing_images: Annotated[
        list[UploadFile],
        File(description="카테고리 순서와 동일한 순서로 첨부할 의류 상품 이미지 파일들 (최대 5개, 파일당 15MB 이하)"),
    ],
) -> Response:
    if len(clothing_images) > len(SUPPORTED_CATEGORIES):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"첨부 가능한 의류 이미지는 최대 {len(SUPPORTED_CATEGORIES)}개입니다.",
        )

    try:
        raw_images: list[bytes] = []
        for index, upload in enumerate(clothing_images):
            chunk = await upload.read(MAX_FILE_SIZE_BYTES + 1)
            if len(chunk) > MAX_FILE_SIZE_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{index + 1}번째 이미지 파일 크기가 제한({MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB)을 초과했습니다.",
                )
            if not chunk:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"{index + 1}번째 이미지 파일이 비어 있습니다.",
                )
            raw_images.append(chunk)

        # 이벤트 루프 차단을 방지하기 위해 동기 함수인 generate_tryon_image를 스레드 풀에서 실행
        output_png = await run_in_threadpool(
            generate_tryon_image,
            categories=categories_json,
            clothing_images=raw_images,
        )

        return Response(
            content=output_png,
            media_type="image/png",
            headers={"Content-Disposition": 'inline; filename="vton-result.png"'},
        )
    except VtonValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Image.DecompressionBombError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="해상도가 비정상적으로 큰 이미지(Decompression Bomb)는 처리할 수 없습니다.",
        ) from exc
    except VtonConfigurationError as exc:
        logger.error("VTON 서버 설정 오류: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="가상 피팅 서비스 환경 설정 오류가 발생했습니다. 관리자에게 문의하세요.",
        ) from exc
    except VtonUpstreamError as exc:
        logger.error("VTON OpenAI API 호출 오류: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI 이미지 생성 서버와의 통신에 실패했습니다.",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("VTON 예기치 않은 오류 발생: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="가상 피팅 처리 중 일시적인 오류가 발생했습니다.",
        ) from exc
    finally:
        for upload in clothing_images:
            await upload.close()
