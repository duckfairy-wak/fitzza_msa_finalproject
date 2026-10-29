"""추천 결과 및 코디 조합 응답 데이터 가공 서비스."""

from __future__ import annotations

import logging
from typing import Any

from app.clients.storage_client import StorageClient, get_storage_client
from app.schemas.recommendation import (
    InternalComboProductItem,
    InternalComboResponse,
    RecommendationDetailResponse,
    RecommendedComboItem,
    RecommendedProductItem,
)

logger = logging.getLogger(__name__)


class RecommendationDetailService:
    """추천 상세 결과 및 코디 조합 DTO 생성과 이미지 URL 해결을 담당하는 서비스."""

    def __init__(self, storage_client: StorageClient | None = None) -> None:
        self._storage_client = storage_client

    @property
    def storage(self) -> StorageClient:
        if self._storage_client is None:
            self._storage_client = get_storage_client()
        return self._storage_client

    def resolve_image_url(self, raw_url_or_key: str | None) -> str | None:
        """S3 키 또는 이미지 URL을 서명 URL로 변환합니다."""
        if not raw_url_or_key or not str(raw_url_or_key).strip():
            return None
        return self.storage.get_presigned_url(str(raw_url_or_key).strip()) or None

    def _resolve_item_dict(self, item_data: dict[str, Any]) -> dict[str, Any]:
        """단일 아이템 딕셔너리의 이미지 URL을 해결한 복사본을 반환합니다."""
        raw = (
            item_data.get("imageKey")
            or item_data.get("image_key")
            or item_data.get("imageUrl")
            or item_data.get("image_url")
        )
        if raw:
            item_copy = dict(item_data)
            item_copy["imageUrl"] = self.resolve_image_url(raw)
            return item_copy
        return item_data

    def build_detail_response(self, record: dict[str, Any]) -> RecommendationDetailResponse:
        """저장소의 추천 레코드를 RecommendationDetailResponse DTO로 변환합니다."""
        items = [
            RecommendedProductItem(**self._resolve_item_dict(item))
            for item in record.get("items") or []
        ]
        combos = []
        for combo in record.get("combos") or []:
            combo_items = [
                RecommendedProductItem(**self._resolve_item_dict(i))
                for i in combo.get("items") or []
            ]
            combos.append(RecommendedComboItem(**{**combo, "items": combo_items}))

        return RecommendationDetailResponse(
            requestId=record["requestId"],
            queryText=str(record.get("queryText") or ""),
            status=record["status"],
            searchType=record.get("searchType"),
            tpoSummary=record.get("tpoSummary"),
            items=items,
            combos=combos,
            message=record.get("message"),
        )

    def build_internal_combo_response(self, combo: dict[str, Any]) -> InternalComboResponse:
        """코디 조합 레코드를 InternalComboResponse DTO로 변환합니다."""
        mapped_items = [
            InternalComboProductItem(
                productId=item.get("productId") or 0,
                productName=item.get("productName") or "",
                price=item.get("price") or 0,
                imageUrl=self.resolve_image_url(
                    item.get("imageKey")
                    or item.get("image_key")
                    or item.get("imageUrl")
                    or item.get("image_url")
                ),
            )
            for item in combo.get("items") or []
        ]

        return InternalComboResponse(
            owned=True,
            items=mapped_items,
            totalPrice=combo.get("totalPrice"),
            feedbackSummary=combo.get("feedbackSummary"),
        )


_RECOMMENDATION_DETAIL_SERVICE: RecommendationDetailService | None = None


def get_recommendation_detail_service() -> RecommendationDetailService:
    """RecommendationDetailService 싱글톤 인스턴스를 반환합니다."""
    global _RECOMMENDATION_DETAIL_SERVICE
    if _RECOMMENDATION_DETAIL_SERVICE is None:
        _RECOMMENDATION_DETAIL_SERVICE = RecommendationDetailService()
    return _RECOMMENDATION_DETAIL_SERVICE
