"""vton-service API 라우터."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Annotated, Any

import json
from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.clients.notification_client import NotificationServiceClient
from app.clients.product_client import ProductServiceClient
from app.clients.sqs_client import SqsClient
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
)
from app.services.vton_generator import (
    SUPPORTED_CATEGORIES,
    VtonConfigurationError,
    VtonError,
    VtonUpstreamError,
    VtonValidationError,
    generate_tryon_image,
    load_sample_clothing_png,
    to_png_bytes,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# 전역 의존성 인스턴스 (테스트 시 주입/교체 가능)
_REPO: VtonRepository | None = None
_PRODUCT_CLIENT: ProductServiceClient | None = None
_NOTIFICATION_CLIENT: NotificationServiceClient | None = None
_STORAGE_CLIENT: StorageClient | None = None
_SQS_CLIENT: SqsClient | None = None


def get_repo() -> VtonRepository:
    global _REPO
    if _REPO is None:
        settings = get_settings()
        _REPO = VtonRepository(
            db_path=settings.db_path,
            postgres_dsn=settings.get_postgres_dsn(),
            postgres_schema=settings.postgres_schema,
        )
    return _REPO


def get_product_client() -> ProductServiceClient:
    global _PRODUCT_CLIENT
    if _PRODUCT_CLIENT is None:
        _PRODUCT_CLIENT = ProductServiceClient()
    return _PRODUCT_CLIENT


def get_notification_client() -> NotificationServiceClient:
    global _NOTIFICATION_CLIENT
    if _NOTIFICATION_CLIENT is None:
        _NOTIFICATION_CLIENT = NotificationServiceClient()
    return _NOTIFICATION_CLIENT


def get_storage_client() -> StorageClient:
    global _STORAGE_CLIENT
    if _STORAGE_CLIENT is None:
        _STORAGE_CLIENT = StorageClient()
    return _STORAGE_CLIENT


def get_sqs_client() -> SqsClient:
    global _SQS_CLIENT
    if _SQS_CLIENT is None:
        _SQS_CLIENT = SqsClient()
    return _SQS_CLIENT


def set_dependencies_for_tests(
    repo: VtonRepository | None = None,
    product_client: ProductServiceClient | None = None,
    notification_client: NotificationServiceClient | None = None,
    storage_client: StorageClient | None = None,
    sqs_client: SqsClient | None = None,
) -> None:
    global _REPO, _PRODUCT_CLIENT, _NOTIFICATION_CLIENT, _STORAGE_CLIENT, _SQS_CLIENT
    _REPO = repo
    _PRODUCT_CLIENT = product_client
    _NOTIFICATION_CLIENT = notification_client
    _STORAGE_CLIENT = storage_client
    _SQS_CLIENT = sqs_client



def _resolve_result_image_url(fitting_id: int, request: Request | None) -> str:
    storage = get_storage_client()
    if storage.is_s3:
        return storage.get_public_url(f"fittings/{fitting_id}.png")
    settings = get_settings()
    if settings.public_base_url.strip():
        base = settings.public_base_url.rstrip("/")
        return f"{base}/api/vton/{fitting_id}/image"
    return f"/api/vton/{fitting_id}/image"


def _resolve_user_image_url(fitting_id: int, request: Request | None) -> str:
    settings = get_settings()
    if settings.public_base_url.strip():
        base = settings.public_base_url.rstrip("/")
        return f"{base}/api/vton/{fitting_id}/user-image"
    return f"/api/vton/{fitting_id}/user-image"


def _run_background_vton(
    fitting_id: int,
    user_id: int,
    photo_id: int | None,
    product_ids: list[int],
    result_image_url: str,
    request_id_header: str | None = None,
    user_face_bytes: bytes | None = None,
    item_image_urls: dict[int, str] | None = None,
) -> bool:
    """백그라운드에서 상품 조회, AI 피팅 합성, 결과 이미지 저장, DB 업데이트 및 FCM 알림을 수행합니다."""
    settings = get_settings()
    repo = get_repo()
    prod_client = get_product_client()
    notif_client = get_notification_client()

    logger.info("비동기 가상 피팅 시작 (fittingId=%s, userId=%s)", fitting_id, user_id)

    try:
        # 1. 상품 정보 및 이미지 수집 (기본 5대 카테고리 매핑)
        used_categories: set[str] = set()
        resolved_products: list[dict[str, Any]] = []

        for pid in product_ids:
            # 사용되지 않은 후보 카테고리 선정
            fallback_category = next(
                (c for c in SUPPORTED_CATEGORIES if c not in used_categories),
                "상의",
            )
            override_url = (item_image_urls or {}).get(pid)
            item = prod_client.resolve_product_item(
                pid,
                fallback_category=fallback_category,
                request_id_header=request_id_header,
                override_image_url=override_url,
            )
            cat = item.get("categoryName") or "상의"
            if cat in used_categories:
                raise VtonValidationError(
                    f"같은 카테고리({cat})의 상품은 하나만 피팅할 수 있습니다."
                )
            used_categories.add(cat)
            resolved_products.append(item)

        # 상품 DB 영속화 (사용자가 요청한 실제 상품들만 DB에 저장)
        repo.save_fitting_products(fitting_id, resolved_products)

        categories = [p["categoryName"] for p in resolved_products]
        clothing_images = [p["imageBytes"] for p in resolved_products]

        # 1-1. 필수 카테고리(하의) 누락 시 기본 베이직 하의 샘플 이미지 자동 보완 (AI 생성 입력에만 추가)
        if "하의" not in used_categories:
            try:
                sample_bottom_bytes = load_sample_clothing_png("하의")
                categories.append("하의")
                clothing_images.append(sample_bottom_bytes)
                logger.info("하의 누락 감지 -> 기본 베이직 하의 이미지 자동 폴백 적용 (fittingId=%s)", fitting_id)
            except Exception as e:
                logger.warning("기본 하의 샘플 로드 실패: %s", e)

        # 1-2. 사용자 얼굴 이미지 로드 (직접 전달받은 바이트가 없고 photo_id가 있는 경우에만 스토리지 다운로드)
        if user_face_bytes is None and photo_id is not None:
            photo_info = repo.get_user_photo(photo_id)
            if not photo_info or not photo_info.get("filePath"):
                raise VtonValidationError(f"지정된 사용자 이미지(photoId={photo_id}) 정보를 찾을 수 없습니다.")

            file_ref = photo_info["filePath"]
            try:
                storage = get_storage_client()
                user_face_bytes = storage.download_bytes(file_ref)
                logger.info(
                    "사용자 얼굴 사진 적용 (photoId=%s, ref=%s, size=%d)",
                    photo_id,
                    file_ref,
                    len(user_face_bytes),
                )
            except Exception as exc:
                logger.error(
                    "사용자 얼굴 사진 파일 로드 실패 (photoId=%s, ref=%s): %s",
                    photo_id,
                    file_ref,
                    exc,
                )
                raise VtonValidationError(f"사용자 이미지(photoId={photo_id})를 불러오는 데 실패했습니다.") from exc
        elif user_face_bytes is not None:
            logger.info(
                "메모리 상의 사용자 얼굴 사진 직접 전달 적용 (photoId=%s, size=%d)",
                photo_id,
                len(user_face_bytes),
            )

        # 2. OpenAI 이미지 편집 피팅 실행 (아바타 몸 + 사용자 얼굴 + 의류)
        output_png = generate_tryon_image(
            categories=categories,
            clothing_images=clothing_images,
            avatar_bytes=None,  # 기본 아바타 몸(avatar.png) 사용
            user_face_bytes=user_face_bytes,
            model=settings.openai_image_model,
            api_key=settings.openai_api_key or None,
            timeout_seconds=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )

        # 3. 결과 이미지 스토리지 저장 (S3 또는 Local Fallback)
        storage = get_storage_client()
        result_key = f"fittings/{fitting_id}.png"
        uploaded_result_url = storage.upload_bytes(result_key, output_png, content_type="image/png")

        # 3-1. 로컬 fallback을 위한 디스크 복제본 저장 (FileResponse 호환 보장)
        try:
            storage_dir = Path(settings.storage_dir)
            storage_dir.mkdir(parents=True, exist_ok=True)
            image_file = storage_dir / f"{fitting_id}.png"
            image_file.write_bytes(output_png)
        except Exception as file_exc:
            logger.warning("로컬 피팅 파일 캐시 저장 건너뜀 (fittingId=%s): %s", fitting_id, file_exc)

        # 4. DB 상태 완료(COMPLETED) 갱신
        final_image_url = uploaded_result_url if storage.is_s3 else result_image_url
        repo.mark_completed(fitting_id, result_image_url=final_image_url)

        # 5. notification-service 피팅 완료 FCM 알림 전송
        notif_client.send_fitting_done(
            user_id=user_id,
            fitting_id=fitting_id,
            request_id_header=request_id_header,
        )
        logger.info("비동기 가상 피팅 성공 완료 (fittingId=%s)", fitting_id)
        return True

    except Exception as exc:
        err_msg = str(exc) or type(exc).__name__
        logger.error(
            "가상 피팅 백그라운드 처리 실패 (fittingId=%s, userId=%s): %s",
            fitting_id,
            user_id,
            err_msg,
            exc_info=True,
        )
        # 내부 시스템 경로 등 상세 스택트레이스를 숨기고 정제된 안내 메시지 저장
        user_error_message = (
            str(exc)
            if isinstance(exc, VtonValidationError)
            else "가상 피팅 생성 중 오류가 발생했습니다."
        )
        repo.mark_failed(fitting_id, error_message=user_error_message)
        notif_client.send_fitting_failed(
            user_id=user_id,
            fitting_id=fitting_id,
            request_id_header=request_id_header,
        )
        return False


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
    limit: Annotated[int, Query(ge=1, le=100, description="조회 건수")] = 20,
    offset: Annotated[int, Query(ge=0, description="시작 위치")] = 0,
    x_user_id: Annotated[int | None, Header(alias="X-User-Id", description="게이트웨이 인증 사용자 ID")] = None,
) -> FittingListResponse:
    if not x_user_id or x_user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요한 서비스입니다.",
        )

    repo = get_repo()
    raw_items, total_count = repo.get_user_fittings(user_id=x_user_id, limit=limit, offset=offset)

    items: list[FittingSummaryResponse] = []
    for item in raw_items:
        user_img_url = _resolve_user_image_url(item["fittingId"], request) if item.get("photoId") else None
        items.append(
            FittingSummaryResponse(
                fittingId=item["fittingId"],
                userId=item["userId"],
                requestId=item.get("requestId"),
                status=item["status"],
                resultImageUrl=item["resultImageUrl"] if item["status"] == "COMPLETED" else None,
                userImageUrl=user_img_url,
                productCount=item.get("productCount", len(item.get("products", []))),
                products=item.get("products", []),
                createdAt=item["createdAt"],
            )
        )

    return FittingListResponse(items=items, totalCount=total_count)


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
                                "minItems": 1,
                                "maxItems": 5,
                                "description": "피팅할 상품 및 추천 색상별 이미지 목록 (최소 1개, 최대 5개)",
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
                validated_req = FittingCreateRequest(items=loaded_items)
                product_ids = validated_req.productIds or []
                for it in (validated_req.items or []):
                    if it.imageUrl and it.imageUrl.strip():
                        item_image_urls[it.productId] = it.imageUrl.strip()
            except (ValueError, TypeError, json.JSONDecodeError, ValidationError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="items는 유효한 JSON 배열 형식이어야 합니다.",
                ) from exc
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
                    detail="productIds는 1개 이상 5개 이하의 유효한 정수 배열이어야 합니다.",
                ) from exc
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="productIds 또는 items가 누락되었습니다.",
            )

        # 상품 검증 선행: 중복 제거 및 최대 개수 확인 (실패 시 이미지 I/O 자체를 방지)
        unique_product_ids = list(dict.fromkeys(product_ids))
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
                detail="최소 하나 이상의 상품 ID를 전달해야 합니다.",
            )

        unique_product_ids = list(dict.fromkeys(product_ids))
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
        sqs_client.send_message(sqs_payload)
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
    fittingId: int,
    x_user_id: Annotated[int | None, Header(alias="X-User-Id", description="게이트웨이 인증 사용자 ID")] = None,
) -> FittingDetailResponse:
    if not x_user_id or x_user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요한 서비스입니다.",
        )

    repo = get_repo()
    detail = repo.get_fitting_detail(fittingId)
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

    user_img_url = _resolve_user_image_url(detail["fittingId"], None) if detail.get("photoId") else None
    return FittingDetailResponse(
        fittingId=detail["fittingId"],
        userId=detail["userId"],
        requestId=detail.get("requestId"),
        userImageUrl=user_img_url,
        status=detail["status"],
        resultImageUrl=detail["resultImageUrl"] if detail["status"] == "COMPLETED" else None,
        errorMessage=detail["errorMessage"],
        products=detail["products"],
        createdAt=detail["createdAt"],
        updatedAt=detail["updatedAt"],
    )


@router.delete(
    "/api/vton/{fittingId}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="가상 피팅 기록 삭제 (소프트 삭제)",
    description="본인의 가상 피팅 기록을 삭제(소프트 삭제)합니다. 삭제된 피팅은 상세 조회 및 이미지 서빙이 차단됩니다.",
)
def delete_fitting(
    fittingId: int,
    x_user_id: Annotated[int | None, Header(alias="X-User-Id", description="게이트웨이 인증 사용자 ID")] = None,
) -> Response:
    if not x_user_id or x_user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요한 서비스입니다.",
        )

    repo = get_repo()
    detail = repo.get_fitting_detail(fittingId, include_deleted=True)
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

    deleted = repo.delete_fitting(fitting_id=fittingId, user_id=x_user_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않거나 이미 삭제된 가상 피팅입니다.",
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/api/vton/{fittingId}/image",
    summary="가상 피팅 결과 PNG 이미지 서빙",
    description="피팅이 완료된 실제 바이너리 PNG 이미지를 브라우저나 앱에서 바로 렌더링할 수 있도록 반환합니다.",
    responses={
        200: {"content": {"image/png": {}}, "description": "가상 피팅 완성 PNG 이미지"},
        404: {"description": "이미지를 찾을 수 없거나 아직 생성되지 않음/삭제됨"},
    },
)
def get_fitting_image(fittingId: int) -> Response:
    # 1. DB에서 삭제 여부 및 상태 선행 검증 (삭제된 피팅 방어)
    repo = get_repo()
    detail = repo.get_fitting_detail(fittingId)
    if not detail or detail.get("isDeleted"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않거나 삭제된 가상 피팅입니다.",
        )
    if detail["status"] != "COMPLETED":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"가상 피팅이 아직 완료되지 않았습니다. 현재 상태: {detail['status']}",
        )

    settings = get_settings()
    storage_dir = Path(settings.storage_dir)
    image_file = storage_dir / f"{fittingId}.png"

    if image_file.is_file():
        return FileResponse(
            path=str(image_file),
            media_type="image/png",
            headers={"Content-Disposition": f'inline; filename="fitting-{fittingId}.png"'},
        )

    # 로컬 캐시에 없을 경우 스토리지 클라이언트(S3)에서 스트리밍 조회 시도
    storage = get_storage_client()
    try:
        img_bytes = storage.download_bytes(f"fittings/{fittingId}.png")
        return Response(
            content=img_bytes,
            media_type="image/png",
            headers={"Content-Disposition": f'inline; filename="fitting-{fittingId}.png"'},
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
    fittingId: int,
    x_user_id: Annotated[int | None, Header(alias="X-User-Id", description="게이트웨이 인증 사용자 ID")] = None,
) -> Response:
    if not x_user_id or x_user_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="로그인이 필요한 서비스입니다.",
        )

    repo = get_repo()
    detail = repo.get_fitting_detail(fittingId)
    if not detail or detail.get("isDeleted"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="존재하지 않거나 삭제된 가상 피팅입니다.",
        )

    # 본인 피팅인지 검증 (타인 얼굴 사진 열람 차단 / IDOR 방어)
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
    fittingId: int,
    userId: int,
    x_service_token: Annotated[str | None, Header(alias="X-Service-Token")] = None,
) -> InternalFittingResponse:
    settings = get_settings()
    if not settings.verify_service_token(x_service_token, allowed_callers=["community"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="유효하지 않은 서비스 토큰입니다.",
        )

    repo = get_repo()
    detail = repo.get_fitting_detail(fittingId)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="피팅 정보를 찾을 수 없습니다.",
        )

    is_owned = (detail["userId"] == userId)
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
