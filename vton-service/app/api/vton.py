"""vton-service API 라우터."""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path as FilePath
from typing import Annotated, Any
import uuid
from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    Header,
    HTTPException,
    Path,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.clients.notification_client import NotificationServiceClient
from app.clients.product_client import ProductServiceClient
from app.clients.sqs_client import SqsClient, SqsClientError
from app.clients.storage_client import StorageClient
from app.core.config import Settings, get_settings
from app.core.database import VtonRepository
from app.schemas.tryon import (
    FittingCreateRequest,
    FittingCreateResponse,
    FittingDetailResponse,
    FittingListResponse,
    FittingSummaryResponse,
    InternalFittingResponse,
    InternalTokenUsageResponse,
)
from app.services.vton_generator import (
    SUPPORTED_CATEGORIES,
    TryonResult,
    VtonConfigurationError,
    VtonError,
    VtonUpstreamError,
    VtonValidationError,
    generate_tryon_image,
    load_sample_clothing_png,
    to_png_bytes,
)
from app.services.vton_processor import (
    build_fitting_detail_response,
    get_notification_client,
    get_product_client,
    get_repo,
    get_sqs_client,
    get_storage_client,
    resolve_result_image_url as _resolve_result_image_url,
    resolve_user_image_url as _resolve_user_image_url,
    run_background_vton as _service_run_background_vton,
    set_dependencies_for_tests,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _run_background_vton(
    fitting_id: int,
    user_id: int,
    photo_id: int | None,
    product_ids: list[int],
    result_image_url: str,
    request_id_header: str | None = None,
    user_face_bytes: bytes | None = None,
    item_image_urls: dict[int, str] | None = None,
    finalize_failure: bool = True,
) -> bool:
    """서비스 계층의 가상 피팅 백그라운드 파이프라인을 호출합니다."""
    return _service_run_background_vton(
        fitting_id=fitting_id,
        user_id=user_id,
        photo_id=photo_id,
        product_ids=product_ids,
        result_image_url=result_image_url,
        request_id_header=request_id_header,
        user_face_bytes=user_face_bytes,
        item_image_urls=item_image_urls,
        finalize_failure=finalize_failure,
        generate_fn=generate_tryon_image,
    )


MAX_PHOTO_SIZE_BYTES = 15 * 1024 * 1024  # 15MB
ALLOWED_PHOTO_EXTENSIONS = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


@router.get(
    "/api/vton",
    response_model=FittingListResponse,
    summary="사용자 가상 피팅 결과 목록 조회",
    description="로그인한 사용자의 활성 가상 피팅 결과 목록을 최신순으로 조회합니다.",
)
def list_user_fittings(
    request: Request,
    request_id: Annotated[
        int | None,
        Query(alias="requestId", ge=1, description="추천 대화 ID (대화별 피팅 필터링)"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100, description="조회 건수")] = 20,
    offset: Annotated[int, Query(ge=0, description="시작 위치")] = 0,
    page: Annotated[int | None, Query(ge=0, description="페이지 번호 (0부터 시작, page 지정 시 offset 자동 계산)")] = None,
    size: Annotated[int | None, Query(ge=1, le=100, description="페이지 크기 (기본값: limit)")] = None,
    x_user_id: Annotated[int | None, Header(alias="X-User-Id", description="게이트웨이 인증 사용자 ID")] = None,
) -> FittingListResponse:
    if not x_user_id or x_user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요한 서비스입니다.",
        )

    # page / size 지원 (타 마이크로서비스 표준 페이징 연동)
    effective_limit = size if size is not None else limit
    effective_offset = (page * effective_limit) if page is not None else offset
    if page is not None:
        current_page = page
    elif effective_limit > 0 and (offset % effective_limit == 0):
        current_page = offset // effective_limit
    else:
        current_page = None

    repo = get_repo()
    raw_items, total_count = repo.get_user_fittings(
        user_id=x_user_id,
        limit=effective_limit,
        offset=effective_offset,
        request_id=request_id,
    )

    storage = get_storage_client()
    items: list[FittingSummaryResponse] = []
    for item in raw_items:
        raw_res_url = item.get("resultImageUrl")
        if item.get("status") == "COMPLETED" and raw_res_url:
            target_key = (
                f"fittings/{item['fittingId']}.png"
                if storage.is_s3 and raw_res_url.startswith("/api/vton/")
                else raw_res_url
            )
            res_img_url = storage.get_presigned_url(target_key)
        else:
            res_img_url = None
        resolved_products = [
            {
                **p,
                "imageUrl": storage.get_presigned_url(p.get("imageUrl")) if p.get("imageUrl") else p.get("imageUrl", ""),
            }
            for p in item.get("products", [])
        ]
        items.append(
            FittingSummaryResponse(
                fittingId=item["fittingId"],
                userId=item["userId"],
                requestId=item.get("requestId"),
                status=item["status"],
                resultImageUrl=res_img_url,
                productCount=item.get("productCount", len(resolved_products)),
                products=resolved_products,
                createdAt=item["createdAt"],
            )
        )

    has_next = (effective_offset + len(items)) < total_count
    total_pages = math.ceil(total_count / effective_limit) if effective_limit > 0 else 0

    return FittingListResponse(
        items=items,
        totalCount=total_count,
        page=current_page,
        size=effective_limit,
        totalPages=total_pages,
        hasNext=has_next,
    )


@router.post(
    "/api/vton",
    response_model=FittingCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="가상 피팅 생성 요청 (비동기)",
    description=(
        "상품 ID 목록과 선택적인 사용자 얼굴 이미지(userImage)를 받아 가상 피팅 작업을 즉시 큐잉(202 Accepted)하고, "
        "백그라운드에서 AI 이미지 합성을 수행한 후 완료 알림을 발송합니다. "
        "JSON 요청 또는 multipart/form-data(userImage 파일 첨부) 모두 지원합니다."
    ),
    openapi_extra={
        "requestBody": {
            "required": True,
            "description": "JSON 본문(피팅할 상품 items 목록) 또는 multipart/form-data(상품 items 목록 + 사용자 얼굴/상반신 이미지)",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["items"],
                        "properties": {
                            "requestId": {
                                "type": "integer",
                                "nullable": True,
                                "description": "추천 요청 ID (추천 대화 연동용)",
                                "example": 6,
                            },
                            "photoId": {
                                "type": "integer",
                                "nullable": True,
                                "description": "사용자 사진 ID (마네킹 아바타로 피팅 시 null)",
                                "example": None,
                            },
                            "items": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "required": ["productId"],
                                    "properties": {
                                        "productId": {
                                            "type": "integer",
                                            "description": "상품 ID",
                                            "example": 101,
                                        },
                                        "imageUrl": {
                                            "type": "string",
                                            "description": "추천된 특정 색상의 상품 이미지 URL",
                                            "example": "https://image.msscdn.net/images/goods_img/green.jpg",
                                        },
                                    },
                                },
                                "minItems": 2,
                                "maxItems": 5,
                                "description": "피팅할 상품 및 추천 색상별 이미지 목록 (최소 2개, 최대 5개)",
                                "example": [
                                    {"productId": 101, "imageUrl": "https://image.msscdn.net/images/goods_img/green.jpg"},
                                    {"productId": 201, "imageUrl": "https://image.msscdn.net/images/goods_img/black.jpg"},
                                ],
                            },
                        },
                    }
                },
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["items"],
                        "properties": {
                            "requestId": {
                                "type": "integer",
                                "description": "추천 요청 ID (추천 대화 연동용)",
                                "example": 6,
                            },
                            "items": {
                                "type": "string",
                                "description": "피팅할 상품 및 추천 색상별 이미지 목록 JSON 문자열 (예: '[{\"productId\": 101, \"imageUrl\": \"https://...\"}]')",
                                "example": '[{"productId": 101, "imageUrl": "https://image.msscdn.net/images/goods_img/green.jpg"}]',
                            },
                            "userImage": {
                                "type": "string",
                                "format": "binary",
                                "description": "사용자 얼굴/상반신 이미지 파일 (PNG, JPEG, WebP 지원)",
                            },
                        },
                    }
                },
            },
        }
    },
)
async def request_fitting(
    request: Request,
    background_tasks: BackgroundTasks,
    x_user_id: Annotated[int | None, Header(alias="X-User-Id", description="게이트웨이 인증 사용자 ID")] = None,
    x_request_id: Annotated[str | None, Header(alias="X-Request-Id")] = None,
) -> FittingCreateResponse:
    if not x_user_id or x_user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요한 서비스입니다.",
        )

    content_type = request.headers.get("content-type", "").lower()
    product_ids: list[int] = []
    photo_id: int | None = None
    request_id: int | None = None
    user_face_bytes: bytes | None = None
    item_image_urls: dict[int, str] = {}

    # 1. 멀티파트 폼 데이터 처리 (userImage 파일 업로드와 productIds/items 동시 수신)
    if "multipart/form-data" in content_type:
        form = await request.form()
        raw_req_id = form.get("requestId")
        if raw_req_id is not None and str(raw_req_id).strip():
            try:
                request_id = int(str(raw_req_id).strip())
            except (ValueError, TypeError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="requestId는 유효한 정수여야 합니다.",
                ) from exc
        raw_items_str = form.get("items")
        raw_values = form.getlist("productIds")

        if raw_items_str and isinstance(raw_items_str, str) and raw_items_str.strip():
            try:
                loaded_items = json.loads(raw_items_str.strip())
                if not isinstance(loaded_items, list):
                    raise ValueError("items는 JSON 배열이어야 합니다.")
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="items는 유효한 JSON 배열 형식이어야 합니다.",
                ) from exc

            try:
                validated_req = FittingCreateRequest(items=loaded_items)
                product_ids = validated_req.productIds or []
                for it in (validated_req.items or []):
                    if it.imageUrl and it.imageUrl.strip():
                        item_image_urls[it.productId] = it.imageUrl.strip()
            except ValidationError as exc:
                raise RequestValidationError(exc.errors()) from exc
        elif raw_values:
            parsed_pids: list[Any] = []
            try:
                for raw in raw_values:
                    if isinstance(raw, str):
                        cleaned = raw.strip()
                        if cleaned.startswith("["):
                            loaded = json.loads(cleaned)
                            if not isinstance(loaded, list):
                                raise ValueError("JSON 배열 형식이어야 합니다.")
                            parsed_pids.extend(loaded)
                        else:
                            parsed_pids.extend(
                                [x.strip() for x in cleaned.split(",") if x.strip()]
                            )
                    else:
                        raise TypeError("productIds는 문자열이어야 합니다.")

                # Pydantic 모델로 productIds 유효성 및 개수 제약(1~5개 정수) 검증
                validated_req = FittingCreateRequest(productIds=parsed_pids)
                product_ids = validated_req.productIds or []
            except (ValueError, TypeError, json.JSONDecodeError, ValidationError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="productIds는 2개 이상 5개 이하의 유효한 정수 배열이어야 합니다.",
                ) from exc
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="productIds 또는 items가 누락되었습니다.",
            )

        # 상품 검증 선행: 중복 제거 및 최소/최대 개수 확인 (실패 시 이미지 I/O 자체를 방지)
        unique_product_ids = list(dict.fromkeys(product_ids))
        if len(unique_product_ids) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="가상 피팅을 위해 최소 2개 이상의 서로 다른 상품을 선택해야 합니다.",
            )
        if len(unique_product_ids) > len(SUPPORTED_CATEGORIES):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"피팅 가능한 상품은 최대 {len(SUPPORTED_CATEGORIES)}개입니다.",
            )

        # 상품 검증 통과 후 userImage 파일 저장 수행
        user_image_file = form.get("userImage")
        if user_image_file and hasattr(user_image_file, "read"):
            content = await user_image_file.read(MAX_PHOTO_SIZE_BYTES + 1)
            if content:
                if len(content) > MAX_PHOTO_SIZE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="사용자 사진 파일 크기는 최대 15MB까지 가능합니다.",
                    )
                try:
                    png_bytes = await run_in_threadpool(to_png_bytes, content)
                    user_face_bytes = png_bytes
                except Exception as exc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="유효하지 않은 이미지 파일입니다.",
                    ) from exc

                storage = get_storage_client()
                photo_filename = f"user_{x_user_id}_{uuid.uuid4().hex[:12]}.png"
                photo_key = f"user-images/{x_user_id}/{photo_filename}"

                # S3 또는 로컬 스토리지 업로드
                try:
                    uploaded_ref = await run_in_threadpool(
                        storage.upload_bytes,
                        key=photo_key,
                        data=png_bytes,
                        content_type="image/png",
                    )
                except Exception as exc:
                    logger.error("사용자 사진 스토리지 저장 실패: %s", exc, exc_info=True)
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="사용자 사진 파일 저장 중 오류가 발생했습니다.",
                    ) from exc

                # 로컬 디스크 캐시 복제본 저장 (로컬 fallback 및 개발 호환성)
                try:
                    settings = get_settings()
                    photos_dir = settings.get_photos_dir()
                    photo_path = photos_dir / photo_filename
                    await run_in_threadpool(photo_path.write_bytes, png_bytes)
                except Exception as file_exc:
                    logger.warning("로컬 사용자 사진 캐시 저장 건너뜀 (userId=%s): %s", x_user_id, file_exc)

                repo = get_repo()
                stored_file_path = photo_key if storage.is_s3 else uploaded_ref
                photo_record = repo.save_user_photo(
                    user_id=x_user_id,
                    file_path=stored_file_path,
                )
                photo_id = photo_record["photoId"]
    else:
        # 2. JSON 요청 처리 (기존 스키마 호환)
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="유효하지 않은 JSON 본문입니다.",
            ) from exc

        try:
            req = FittingCreateRequest.model_validate(body)
            product_ids = req.productIds or []
            photo_id = req.photoId
            request_id = req.requestId
            if req.items:
                for it in req.items:
                    if it.imageUrl and it.imageUrl.strip():
                        item_image_urls[it.productId] = it.imageUrl.strip()
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from exc

        if not product_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="최소 2개 이상의 상품 ID를 전달해야 합니다.",
            )

        unique_product_ids = list(dict.fromkeys(product_ids))
        if len(unique_product_ids) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="가상 피팅을 위해 최소 2개 이상의 서로 다른 상품을 선택해야 합니다.",
            )
        if len(unique_product_ids) > len(SUPPORTED_CATEGORIES):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"피팅 가능한 상품은 최대 {len(SUPPORTED_CATEGORIES)}개입니다.",
            )

    repo = get_repo()
    if photo_id is not None:
        photo_info = repo.get_user_photo(photo_id)
        if not photo_info or photo_info.get("userId") != x_user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="등록된 사용자 사진 정보를 찾을 수 없습니다.",
            )

    fitting_id = repo.create_fitting(
        user_id=x_user_id,
        photo_id=photo_id,
        product_ids=unique_product_ids,
        request_id=request_id,
    )

    result_image_url = _resolve_result_image_url(fitting_id, request)

    settings = get_settings()
    if settings.queue_backend == "sqs":
        sqs_client = get_sqs_client()
        sqs_payload = {
            "fitting_id": fitting_id,
            "user_id": x_user_id,
            "photo_id": photo_id,
            "request_id": request_id,
            "product_ids": unique_product_ids,
            "result_image_url": result_image_url,
            "request_id_header": x_request_id,
            "item_image_urls": item_image_urls,
        }
        try:
            sqs_client.send_message(sqs_payload)
        except SqsClientError as exc:
            logger.error(
                "SQS 피팅 작업 발행 실패 (fittingId=%s, userId=%s): %s",
                fitting_id,
                x_user_id,
                exc,
                exc_info=True,
            )
            try:
                repo.update_fitting_failed(
                    fitting_id=fitting_id,
                    error_message="가상 피팅 작업 큐 등록에 실패했습니다.",
                )
            except Exception as db_exc:
                logger.warning(
                    "SQS 발행 실패 후 DB FAILED 상태 전환 중 예외 발생 (fittingId=%s): %s",
                    fitting_id,
                    db_exc,
                )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="가상 피팅 작업 큐 등록에 실패했습니다.",
            ) from exc
        logger.info(
            "SQS 피팅 작업 발행 완료 (queue_backend=sqs, fittingId=%s, userId=%s)",
            fitting_id,
            x_user_id,
        )
    else:
        # 백그라운드 태스크 등록 (QUEUE_BACKEND=memory)
        background_tasks.add_task(
            _run_background_vton,
            fitting_id=fitting_id,
            user_id=x_user_id,
            photo_id=photo_id,
            product_ids=unique_product_ids,
            result_image_url=result_image_url,
            request_id_header=x_request_id,
            user_face_bytes=user_face_bytes,
            item_image_urls=item_image_urls,
        )

    return FittingCreateResponse(fittingId=fitting_id, status="PENDING")


@router.get(
    "/api/vton/{fittingId}",
    response_model=FittingDetailResponse,
    summary="가상 피팅 결과 상세 조회",
    description="피팅 ID로 현재 진행 상태(PENDING/COMPLETED/FAILED) 및 결과 이미지 URL, 상품 목록을 조회합니다.",
)
def get_fitting(
    fitting_id: Annotated[int, Path(alias="fittingId", gt=0, description="피팅 ID")],
    x_user_id: Annotated[int | None, Header(alias="X-User-Id", description="게이트웨이 인증 사용자 ID")] = None,
) -> FittingDetailResponse:
    if not x_user_id or x_user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요한 서비스입니다.",
        )

    repo = get_repo()
    detail = repo.get_fitting_detail(fitting_id)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않는 가상 피팅입니다.",
        )

    # 본인 피팅인지 검증
    if detail["userId"] != x_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인의 피팅 결과만 조회할 수 있습니다.",
        )

    return build_fitting_detail_response(detail)


@router.delete(
    "/api/vton/{fittingId}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="가상 피팅 기록 삭제 (소프트 삭제)",
    description="본인의 가상 피팅 기록을 삭제(소프트 삭제)합니다. 삭제된 피팅은 상세 조회 및 이미지 서빙이 차단됩니다.",
)
def delete_fitting(
    fitting_id: Annotated[int, Path(alias="fittingId", gt=0, description="피팅 ID")],
    x_user_id: Annotated[int | None, Header(alias="X-User-Id", description="게이트웨이 인증 사용자 ID")] = None,
) -> Response:
    if not x_user_id or x_user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요한 서비스입니다.",
        )

    repo = get_repo()
    detail = repo.get_fitting_detail(fitting_id, include_deleted=True)
    if not detail or detail.get("isDeleted"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않거나 이미 삭제된 가상 피팅입니다.",
        )

    if detail["userId"] != x_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인의 피팅 결과만 삭제할 수 있습니다.",
        )

    deleted = repo.delete_fitting(fitting_id=fitting_id, user_id=x_user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않거나 이미 삭제된 가상 피팅입니다.",
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/api/vton/{fittingId}/image",
    summary="가상 피팅 결과 PNG 이미지 서빙",
    description="피팅이 완료된 실제 바이너리 PNG 이미지를 브라우저나 앱에서 바로 렌더링할 수 있도록 반환합니다. 본인 소유 피팅만 접근 가능합니다.",
    responses={
        200: {"content": {"image/png": {}}, "description": "가상 피팅 완성 PNG 이미지"},
        307: {"description": "S3 Pre-signed URL 임시 리다이렉트"},
        401: {"description": "로그인 필요"},
        403: {"description": "본인의 피팅 이미지만 조회 가능"},
        404: {"description": "이미지를 찾을 수 없거나 아직 생성되지 않음/삭제됨"},
    },
)
def get_fitting_image(
    fitting_id: Annotated[int, Path(alias="fittingId", gt=0, description="피팅 ID")],
    x_user_id: Annotated[int | None, Header(alias="X-User-Id", description="게이트웨이 인증 사용자 ID")] = None,
) -> Response:
    storage = get_storage_client()

    # S3 백엔드(운영 환경)인 경우 게이트웨이 인증 필수
    # 로컬 스토리지 모드(storage_backend == "local")인 경우 브라우저 <img> 태그 요청 시
    # Authorization 헤더를 실을 수 없으므로 인증을 건너뛰고 이미지 서빙 허용
    if storage.is_s3:
        if not x_user_id or x_user_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="로그인이 필요한 서비스입니다.",
            )

    # 1. DB에서 삭제 여부 및 상태 선행 검증 (삭제된 피팅 방어)
    repo = get_repo()
    detail = repo.get_fitting_detail(fitting_id)
    if not detail or detail.get("isDeleted"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않거나 삭제된 가상 피팅입니다.",
        )

    # 2. 본인 피팅인지 검증 (S3 운영 환경이거나 x_user_id가 명시된 경우 IDOR 보안 취약점 방어)
    if storage.is_s3 or (x_user_id is not None and x_user_id > 0):
        if detail["userId"] != x_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="본인의 피팅 결과 이미지만 조회할 수 있습니다.",
            )

    if detail["status"] != "COMPLETED":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"가상 피팅이 아직 완료되지 않았습니다. 현재 상태: {detail['status']}",
        )

    # 3. S3 백엔드인 경우 서명 URL로 307 임시 리다이렉트
    if storage.is_s3:
        raw_target = detail.get("resultImageUrl")
        key_or_url = (
            f"fittings/{fitting_id}.png"
            if not raw_target or raw_target.startswith("/api/vton/")
            else raw_target
        )
        presigned_url = storage.get_presigned_url(key_or_url, expires_in=3600)
        if presigned_url.startswith(("http://", "https://")):
            return RedirectResponse(
                url=presigned_url,
                status_code=status.HTTP_307_TEMPORARY_REDIRECT,
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )

    settings = get_settings()
    storage_dir = FilePath(settings.storage_dir)
    image_file = storage_dir / f"{fitting_id}.png"

    if image_file.is_file():
        return FileResponse(
            path=str(image_file),
            media_type="image/png",
            headers={"Content-Disposition": f'inline; filename="fitting-{fitting_id}.png"'},
        )

    # 로컬 캐시에 없을 경우 스토리지 클라이언트(S3/Mock)에서 스트리밍 조회 시도
    try:
        img_bytes = storage.download_bytes(f"fittings/{fitting_id}.png")
        return Response(
            content=img_bytes,
            media_type="image/png",
            headers={"Content-Disposition": f'inline; filename="fitting-{fitting_id}.png"'},
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="피팅 결과 이미지 파일을 찾을 수 없습니다.",
        )


@router.get(
    "/api/vton/{fittingId}/user-image",
    summary="사용자 얼굴/상반신 이미지 파일 서빙 (로컬 개발용)",
    description="가상 피팅 요청 시 첨부했던 사용자 얼굴/상반신 원본 이미지를 브라우저나 앱에서 확인할 수 있도록 스트리밍합니다.",
    responses={
        200: {"content": {"image/png": {}}, "description": "사용자 원본 이미지"},
        404: {"description": "사용자 이미지를 첨부하지 않았거나 이미지를 찾을 수 없음"},
    },
)
def get_fitting_user_image(
    fitting_id: Annotated[int, Path(alias="fittingId", gt=0, description="피팅 ID")],
    x_user_id: Annotated[int | None, Header(alias="X-User-Id", description="게이트웨이 인증 사용자 ID")] = None,
) -> Response:
    storage = get_storage_client()

    # S3 백엔드(운영 환경)인 경우 게이트웨이 인증 필수
    # 로컬 스토리지 모드(storage_backend == "local")인 경우 브라우저 <img> 태그 요청 허용
    if storage.is_s3:
        if not x_user_id or x_user_id <= 0:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="로그인이 필요한 서비스입니다.",
            )

    repo = get_repo()
    detail = repo.get_fitting_detail(fitting_id)
    if not detail or detail.get("isDeleted"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않거나 삭제된 가상 피팅입니다.",
        )

    # 본인 피팅인지 검증 (S3 운영 환경이거나 x_user_id가 명시된 경우 타인 얼굴 사진 열람 차단 / IDOR 방어)
    if storage.is_s3 or (x_user_id is not None and x_user_id > 0):
        if detail["userId"] != x_user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="본인의 피팅 이미지만 조회할 수 있습니다.",
            )

    photo_id = detail.get("photoId")
    if not photo_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 피팅에는 사용자가 등록한 이미지가 없습니다 (기본 아바타 사용).",
        )

    photo_info = repo.get_user_photo(photo_id)
    if not photo_info or not photo_info.get("filePath"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자 사진 정보를 찾을 수 없습니다.",
        )

    file_ref = photo_info["filePath"]
    storage = get_storage_client()
    try:
        user_bytes = storage.download_bytes(file_ref)
        return Response(
            content=user_bytes,
            media_type="image/png",
            headers={"Content-Disposition": f'inline; filename="user-{photo_id}.png"'},
        )
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="사용자 사진 파일이 서버에 존재하지 않습니다.",
        )
    except Exception as exc:
        logger.error("사용자 사진 로드 실패 (photoId=%s, ref=%s): %s", photo_id, file_ref, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="사용자 사진 파일 로드 중 오류가 발생했습니다.",
        )


@router.get(
    "/fittings/{fittingId}",
    response_model=InternalFittingResponse,
    summary="[내부 서비스용] 커뮤니티 공유 유효성 검증",
    description="community-service 전용 내부 API. X-Service-Token 헤더를 검증하고 해당 사용자의 소유권과 상품 목록을 반환합니다.",
)
def get_internal_fitting(
    fitting_id: Annotated[int, Path(alias="fittingId", gt=0, description="피팅 ID")],
    user_id: Annotated[int, Query(alias="userId", gt=0, description="소유권 확인할 사용자 ID")],
    x_service_token: Annotated[str | None, Header(alias="X-Service-Token")] = None,
) -> InternalFittingResponse:
    settings = get_settings()
    if not settings.verify_service_token(x_service_token, allowed_callers=["community"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 서비스 토큰입니다.",
        )

    repo = get_repo()
    detail = repo.get_fitting_detail(fitting_id)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="피팅 정보를 찾을 수 없습니다.",
        )

    is_owned = (detail["userId"] == user_id)
    products_for_community = [
        {
            "productId": p["productId"],
            "productName": p["productName"],
            "price": p["price"],
            "imageUrl": p["imageUrl"],
        }
        for p in detail.get("products", [])
    ]

    return InternalFittingResponse(
        owned=is_owned,
        status=detail["status"],
        resultImageUrl=detail["resultImageUrl"] if detail["status"] == "COMPLETED" else None,
        products=products_for_community,
    )


@router.get(
    "/vton/token-usage",
    response_model=InternalTokenUsageResponse,
    summary="[내부 서비스용] 기간별 가상 피팅 OpenAI 토큰 사용량 집계",
    description="recommendation-service 전용 내부 API. X-Service-Token 헤더를 검증하고 지정된 기간 동안 완료된 피팅의 토큰 사용량 목록을 반환합니다.",
)
def get_internal_token_usage(
    start_date: Annotated[datetime, Query(alias="startDate", description="조회 시작일시 (ISO-8601 UTC)")],
    end_date: Annotated[datetime, Query(alias="endDate", description="조회 종료일시 (ISO-8601 UTC)")],
    x_service_token: Annotated[str | None, Header(alias="X-Service-Token")] = None,
) -> InternalTokenUsageResponse:
    settings = get_settings()
    if not settings.verify_service_token(x_service_token, allowed_callers=["recommendation"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 서비스 토큰입니다.",
        )

    s_dt = start_date if start_date.tzinfo is not None else start_date.replace(tzinfo=timezone.utc)
    e_dt = end_date if end_date.tzinfo is not None else end_date.replace(tzinfo=timezone.utc)
    start_iso = s_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    end_iso = e_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    repo = get_repo()
    records = repo.get_token_usage_in_range(start_iso=start_iso, end_iso=end_iso)
    return InternalTokenUsageResponse(records=records)
