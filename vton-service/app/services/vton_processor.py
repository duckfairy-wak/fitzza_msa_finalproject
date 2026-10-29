"""가상 피팅(VTON) 백그라운드 실행 파이프라인 및 의존성 관리 서비스."""

from __future__ import annotations

import logging
from pathlib import Path
import threading
from typing import Any, Callable

from fastapi import Request

from app.clients.notification_client import NotificationServiceClient
from app.clients.product_client import ProductServiceClient
from app.clients.sqs_client import SqsClient
from app.clients.storage_client import StorageClient
from app.core.config import get_settings
from app.core.database import VtonRepository
from app.schemas.tryon import FittingDetailResponse
from app.services.vton_generator import (
    SUPPORTED_CATEGORIES,
    TryonResult,
    VtonValidationError,
    generate_tryon_image,
    load_sample_clothing_png,
)

logger = logging.getLogger(__name__)

# 전역 의존성 인스턴스 (테스트 시 주입/교체 가능)
_REPO: VtonRepository | None = None
_PRODUCT_CLIENT: ProductServiceClient | None = None
_NOTIFICATION_CLIENT: NotificationServiceClient | None = None
_STORAGE_CLIENT: StorageClient | None = None
_SQS_CLIENT: SqsClient | None = None

_THREAD_STATE = threading.local()


def get_last_vton_error() -> BaseException | None:
    return getattr(_THREAD_STATE, "last_error", None)


def _set_last_vton_error(err: BaseException | None) -> None:
    _THREAD_STATE.last_error = err


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


def resolve_result_image_url(fitting_id: int, request: Request | None = None) -> str:
    storage = get_storage_client()
    if storage.is_s3:
        return storage.get_public_url(f"fittings/{fitting_id}.png")
    settings = get_settings()
    if settings.public_base_url.strip():
        base = settings.public_base_url.rstrip("/")
        return f"{base}/api/vton/{fitting_id}/image"
    return f"/api/vton/{fitting_id}/image"


def resolve_user_image_url(fitting_id: int, request: Request | None = None) -> str:
    settings = get_settings()
    if settings.public_base_url.strip():
        base = settings.public_base_url.rstrip("/")
        return f"{base}/api/vton/{fitting_id}/user-image"
    return f"/api/vton/{fitting_id}/user-image"


def build_fitting_detail_response(detail: dict[str, Any]) -> FittingDetailResponse:
    """피팅 상세 딕셔너리를 받아 S3/CDN Pre-signed URL 및 상품 목록을 조합한 응답 DTO를 생성합니다."""
    storage = get_storage_client()
    fitting_id = detail["fittingId"]
    raw_res_url = detail.get("resultImageUrl")

    if detail.get("status") == "COMPLETED" and raw_res_url:
        target_key = (
            f"fittings/{fitting_id}.png"
            if storage.is_s3 and raw_res_url.startswith("/api/vton/")
            else raw_res_url
        )
        result_img_url = storage.get_presigned_url(target_key)
    else:
        result_img_url = None

    resolved_products = [
        {
            **p,
            "imageUrl": storage.get_presigned_url(p.get("imageUrl")) if p.get("imageUrl") else p.get("imageUrl", ""),
        }
        for p in detail.get("products", [])
    ]

    return FittingDetailResponse(
        fittingId=detail["fittingId"],
        userId=detail["userId"],
        requestId=detail.get("requestId"),
        status=detail["status"],
        resultImageUrl=result_img_url,
        errorMessage=detail["errorMessage"],
        warnings=detail.get("warnings") or [],
        products=resolved_products,
        createdAt=detail["createdAt"],
        updatedAt=detail["updatedAt"],
    )


def run_background_vton(
    fitting_id: int,
    user_id: int,
    photo_id: int | None,
    product_ids: list[int],
    result_image_url: str,
    request_id_header: str | None = None,
    user_face_bytes: bytes | None = None,
    item_image_urls: dict[int, str] | None = None,
    finalize_failure: bool = True,
    generate_fn: Callable[..., Any] | None = None,
) -> bool:
    """백그라운드 피팅을 수행하고 최종 실패(또는 검증 실패)일 때 상태와 알림을 확정합니다."""
    _set_last_vton_error(None)
    settings = get_settings()
    repo = get_repo()
    prod_client = get_product_client()
    notif_client = get_notification_client()
    tryon_fn = generate_fn or generate_tryon_image

    logger.info("비동기 가상 피팅 시작 (fittingId=%s, userId=%s)", fitting_id, user_id)

    try:
        # 1. 상품 정보 및 실제 카테고리 수집 (배열 순서 기반 강제 할당 제거)
        warnings: list[str] = []
        resolved_products: list[dict[str, Any]] = []
        category_to_product: dict[str, dict[str, Any]] = {}

        for pid in product_ids:
            override_url = (item_image_urls or {}).get(pid) or (item_image_urls or {}).get(str(pid))
            item = prod_client.resolve_product_item(
                pid,
                fallback_category=None,
                request_id_header=request_id_header,
                override_image_url=override_url,
            )
            cat = (item.get("categoryName") or "").strip()
            if not cat or cat not in SUPPORTED_CATEGORIES:
                raise VtonValidationError(
                    f"지원하지 않거나 데이터가 동기화되지 않은 상품입니다 (productId={pid}, category={cat})"
                )

            if cat in category_to_product:
                raise VtonValidationError(
                    f"같은 카테고리({cat})의 상품은 하나만 피팅할 수 있습니다."
                )
            category_to_product[cat] = item
            resolved_products.append(item)

        if len(category_to_product) < 2:
            raise VtonValidationError("가상 피팅을 위해 최소 2개 이상의 서로 다른 카테고리 상품이 필요합니다.")

        # 상품 DB 영속화 (사용자가 요청한 실제 상품들만 DB에 저장)
        repo.save_fitting_products(fitting_id, resolved_products)

        # 2. 피팅 합성용 카테고리 및 이미지 번들 구성
        # 정책:
        # - 필수 3종 ("상의", "하의", "신발"): 상품 누락 또는 이미지 다운로드 실패 시 기본 에셋으로 대체 + warning
        # - 선택 품목 ("아우터", "모자"): 이미지 다운로드 실패 시 피팅 합성에서 제외 + warning
        final_categories: list[str] = []
        clothing_images: list[bytes] = []

        # 2-1. 사용자가 요청한 상품별 이미지 처리
        for item in resolved_products:
            cat = item["categoryName"]
            img_bytes = item.get("imageBytes")

            if img_bytes:
                final_categories.append(cat)
                clothing_images.append(img_bytes)
            else:
                # 이미지 다운로드 실패
                if cat in ("상의", "하의", "신발"):
                    try:
                        sample_bytes = load_sample_clothing_png(cat)
                        final_categories.append(cat)
                        clothing_images.append(sample_bytes)
                        msg = f"요청하신 [{cat}] 카테고리 상품 이미지를 불러올 수 없어 기본 에셋으로 대체 피팅되었습니다."
                        warnings.append(msg)
                        logger.info("필수 카테고리(%s) 이미지 실패 -> 기본 에셋 대체 (fittingId=%s)", cat, fitting_id)
                    except Exception as exc:
                        logger.warning("기본 에셋(%s) 로드 실패: %s", cat, exc)
                else:
                    # 선택 품목(아우터, 모자): 제외
                    msg = f"요청하신 [{cat}] 카테고리 상품 이미지를 불러올 수 없어 피팅에서 제외되었습니다."
                    warnings.append(msg)
                    logger.info("선택 카테고리(%s) 이미지 실패 -> 피팅 합성에서 제외 (fittingId=%s)", cat, fitting_id)

        # 2-2. 필수 3종 중 아예 요청에 누락된 카테고리 보완
        for required_cat in ("상의", "하의", "신발"):
            if required_cat not in category_to_product:
                try:
                    sample_bytes = load_sample_clothing_png(required_cat)
                    final_categories.append(required_cat)
                    clothing_images.append(sample_bytes)
                    msg = f"요청에 [{required_cat}] 카테고리가 포함되지 않아 기본 에셋으로 보완 피팅되었습니다."
                    warnings.append(msg)
                    logger.info("필수 카테고리(%s) 누락 감지 -> 기본 에셋 추가 (fittingId=%s)", required_cat, fitting_id)
                except Exception as exc:
                    logger.warning("기본 필수 에셋(%s) 보완 로드 실패: %s", required_cat, exc)

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
        tryon_res = tryon_fn(
            categories=final_categories,
            clothing_images=clothing_images,
            avatar_bytes=None,  # 기본 아바타 몸(avatar.png) 사용
            user_face_bytes=user_face_bytes,
            model=settings.openai_image_model,
            api_key=settings.openai_api_key or None,
            timeout_seconds=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
        )
        if isinstance(tryon_res, TryonResult):
            output_png = tryon_res.image_bytes
            prompt_tokens = tryon_res.prompt_tokens
            completion_tokens = tryon_res.completion_tokens
        else:
            output_png = tryon_res
            prompt_tokens = 0
            completion_tokens = 0

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
        repo.mark_completed(
            fitting_id,
            result_image_url=final_image_url,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            warnings=warnings,
        )

        # 5. notification-service 피팅 완료 FCM 알림 전송
        notif_client.send_fitting_done(
            user_id=user_id,
            fitting_id=fitting_id,
            request_id_header=request_id_header,
        )
        logger.info("비동기 가상 피팅 성공 완료 (fittingId=%s)", fitting_id)
        return True

    except Exception as exc:
        _set_last_vton_error(exc)
        err_msg = str(exc) or type(exc).__name__
        logger.error(
            "가상 피팅 백그라운드 처리 실패 (fittingId=%s, userId=%s): %s",
            fitting_id,
            user_id,
            err_msg,
            exc_info=True,
        )
        is_validation_error = isinstance(exc, VtonValidationError)
        if finalize_failure or is_validation_error:
            user_error_message = (
                str(exc)
                if is_validation_error
                else "가상 피팅 생성 중 오류가 발생했습니다."
            )
            repo.mark_failed(fitting_id, error_message=user_error_message)
            notif_client.send_fitting_failed(
                user_id=user_id,
                fitting_id=fitting_id,
                request_id_header=request_id_header,
            )
        else:
            logger.info(
                "SQS 재시도를 위해 피팅 상태를 PENDING으로 유지합니다 (fittingId=%s)",
                fitting_id,
            )
        return False


_run_background_vton = run_background_vton
_resolve_result_image_url = resolve_result_image_url
_resolve_user_image_url = resolve_user_image_url
