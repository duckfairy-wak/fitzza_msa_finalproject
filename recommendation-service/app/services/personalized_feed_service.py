from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models

from pydantic import ValidationError

from app.core.config import get_settings
from app.schemas.recommendation import (
    PersonalizedPageResponse,
    PersonalizedProductItem,
)
from app.services.personalized_vector_engine import PersonalizedVectorEngine
from app.services.user_history_service import (
    UserActionHistory,
    UserHistoryCollector,
)

logger = logging.getLogger(__name__)


class PersonalizedFeedService:
    """
    사용자 행동 이력 기반 취향 벡터를 생성하고,
    Qdrant에서 5대 카테고리(상의, 하의, 아우터, 신발, 모자)별로 상위 후보군을 검색한 뒤,
    구매 상품 제외 및 라운드 로빈 교차 인터리빙을 거쳐 최종 추천 피드 아이템을 조립하는 서비스.
    """

    CATEGORIES = ["상의", "하의", "아우터", "신발", "모자"]
    ITEMS_PER_CATEGORY = 16  # 5대 카테고리 * 16개 = 총 80개
    TOTAL_ITEMS = 80

    def __init__(
        self,
        qdrant_client: Optional[QdrantClient] = None,
        collection_name: Optional[str] = None,
        vector_engine: Optional[PersonalizedVectorEngine] = None,
        history_collector: Optional[UserHistoryCollector] = None,
        qdrant_url: Optional[str] = None,
    ) -> None:
        settings = get_settings()
        self.collection_name = (
            collection_name or settings.qdrant_collection_name or "musinsa_products"
        )

        if qdrant_client is not None:
            self.client = qdrant_client
        else:
            url = qdrant_url or settings.qdrant_url or "http://localhost:6333"
            self.client = QdrantClient(url=url)

        self.vector_engine = vector_engine or PersonalizedVectorEngine(
            qdrant_client=self.client,
            collection_name=self.collection_name,
        )
        self.history_collector = history_collector or UserHistoryCollector()

    def search_category_candidates(
        self,
        taste_vector: list[float],
        category: str,
        limit: int = 16,
        exclude_pids: Optional[list[int]] = None,
        wishlist_set: Optional[set[int]] = None,
    ) -> list[PersonalizedProductItem]:
        """
        단일 카테고리에 대해 취향 벡터 유사도 상위 상품을 검색한다.
        - 최근 구매 상품(exclude_pids)은 must_not 필터로 Qdrant 레벨에서 원천 제외.
        - 동일 상품(다양한 색상 포인트) 중복 방지를 위해 fetch_limit을 넉넉히 설정 후 중복 제거.
        - wishlist_set을 참조하여 wished 플래그를 세팅.
        """
        wished_ids = wishlist_set or set()
        clean_exclude_ids = (
            [int(pid) for pid in exclude_pids if pid is not None and int(pid) > 0]
            if exclude_pids
            else []
        )

        must_conditions: list[models.FieldCondition] = [
            models.FieldCondition(
                key="category",
                match=models.MatchValue(value=category),
            )
        ]

        must_not_conditions: list[models.FieldCondition] = []
        if clean_exclude_ids:
            must_not_conditions.append(
                models.FieldCondition(
                    key="product_id",
                    match=models.MatchAny(any=clean_exclude_ids),
                )
            )

        query_filter = models.Filter(
            must=must_conditions,
            must_not=must_not_conditions if must_not_conditions else None,
        )

        # 상품당 여러 색상 포인트가 있을 수 있으므로 여유있게 조회
        fetch_limit = max(limit * 3, 30)

        try:
            response = self.client.query_points(
                collection_name=self.collection_name,
                query=taste_vector,
                query_filter=query_filter,
                limit=fetch_limit,
                with_payload=True,
                with_vectors=False,
            )
        except Exception as e:
            logger.error(
                "Qdrant 카테고리(%s) 검색 실패: %s", category, e, exc_info=True
            )
            return []

        items: list[PersonalizedProductItem] = []
        seen_pids: set[int] = set()

        for point in response.points:
            payload = point.payload or {}
            raw_pid = payload.get("product_id")
            if raw_pid is None:
                continue

            try:
                pid = int(raw_pid)
            except (ValueError, TypeError):
                continue

            if pid in seen_pids:
                continue
            seen_pids.add(pid)

            item = PersonalizedProductItem(
                productId=pid,
                productName=str(payload.get("product_name") or ""),
                brandName=payload.get("brand_name"),
                price=int(payload.get("price") or 0),
                thumbnailUrl=payload.get("image_url"),
                status="ON_SALE",
                category=payload.get("category"),
                wished=(pid in wished_ids),
            )
            items.append(item)
            if len(items) >= limit:
                break

        return items

    @classmethod
    def interleave_categories(
        cls,
        category_buckets: dict[str, list[PersonalizedProductItem]],
        order: Optional[list[str]] = None,
        limit_per_category: int = 16,
    ) -> list[PersonalizedProductItem]:
        """
        카테고리별 상품 목록을 라운드 로빈(Round-Robin) 방식으로 교차 결합한다.
        결과 순서: [상의0, 하의0, 아우터0, 신발0, 모자0, 상의1, 하의1, ...]
        특정 카테고리가 조기 소진되면 남은 카테고리들로 순회를 계속한다.
        """
        target_order = order or cls.CATEGORIES
        interleaved: list[PersonalizedProductItem] = []

        for round_idx in range(limit_per_category):
            for cat in target_order:
                items = category_buckets.get(cat, [])
                if round_idx < len(items):
                    interleaved.append(items[round_idx])

        return interleaved

    async def generate_personalized_feed_items(
        self,
        user_id: Optional[int],
    ) -> tuple[list[PersonalizedProductItem], UserActionHistory]:
        """
        사용자 ID를 받아 전체 개인화 피드 아이템(최대 80개)을 조립하여 반환한다.
        1. 비동기 행동 이력 수집 (게스트는 빈 이력)
        2. 취향 벡터 계산 (Cold-Start 포함)
        3. 5대 카테고리 병렬 비동기 Qdrant 검색
        4. 인터리빙 결합
        """
        # 1. 사용자 이력 수집
        if user_id is not None and user_id > 0:
            history = await self.history_collector.collect_user_history_async(user_id)
        else:
            history = UserActionHistory(user_id=0)

        # 2. 취향 벡터 계산 (동기 Qdrant scroll 및 벡터 연산을 스레드풀에서 비동기 실행)
        taste_vector = await asyncio.to_thread(
            self.vector_engine.compute_user_taste_vector,
            history,
        )

        # 3. 제외할 상품 ID (최근 구매 상품) 및 찜 집합
        exclude_pids = list(set(history.purchased_product_ids))
        wishlist_set = set(history.wishlist_product_ids)

        # 4. 5대 카테고리 비동기 동시 병렬 검색 (asyncio.gather)
        tasks = [
            asyncio.to_thread(
                self.search_category_candidates,
                taste_vector=taste_vector,
                category=cat,
                limit=self.ITEMS_PER_CATEGORY,
                exclude_pids=exclude_pids,
                wishlist_set=wishlist_set,
            )
            for cat in self.CATEGORIES
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        category_buckets: dict[str, list[PersonalizedProductItem]] = {}
        for cat, res in zip(self.CATEGORIES, results):
            if isinstance(res, list):
                category_buckets[cat] = res
            else:
                logger.error("카테고리 %s 비동기 검색 실패: %s", cat, res)
                category_buckets[cat] = []

        # 5. 인터리빙 결합
        interleaved_feed = self.interleave_categories(
            category_buckets=category_buckets,
            order=self.CATEGORIES,
            limit_per_category=self.ITEMS_PER_CATEGORY,
        )

        return interleaved_feed, history

    async def get_personalized_feed_page(
        self,
        user_id: int = 0,
        page: int = 0,
        size: int = 20,
        refresh: bool = False,
        cache_service: Optional[Any] = None,
    ) -> PersonalizedPageResponse:
        """
        사용자 ID와 페이징 옵션을 받아 5분 캐시 정책 및 게스트 보호를 적용하여 페이징 피드를 반환한다.
        - 게스트(user_id <= 0): 공통 키 'guest'를 사용하며, refresh=True여도 캐시 무효화를 수행하지 않음 (캐시 보호).
        - 회원(user_id > 0): user_id별 캐시를 사용하며, refresh=True 시 기존 캐시 삭제 후 재생성.
        - 캐시 적중 시: 캐시된 80개 목록에서 슬라이싱하여 반환.
        - 캐시 미스 시: 80개 피드를 생성하여 캐시에 5분(300초) 저장 후 슬라이싱 반환.
        """
        is_guest = (user_id <= 0)
        cache_user_key = "guest" if is_guest else str(user_id)

        # 게스트의 경우 refresh 요청으로 인한 공용 캐시 무효화 방어
        if refresh and not is_guest and cache_service is not None:
            await asyncio.to_thread(cache_service.delete_personalized_feed, cache_user_key)

        all_items: list[PersonalizedProductItem] = []
        if cache_service is not None and (not refresh or is_guest):
            cached_raw = await asyncio.to_thread(
                cache_service.get_personalized_feed, cache_user_key
            )
            if isinstance(cached_raw, list):
                try:
                    all_items = [PersonalizedProductItem(**item) for item in cached_raw]
                except (TypeError, ValidationError) as exc:
                    logger.warning(
                        "개인화 피드 캐시 역직렬화 실패, 재생성합니다 (key=%s): %s",
                        cache_user_key,
                        exc,
                    )
                    all_items = []

        if not all_items:
            all_items, _ = await self.generate_personalized_feed_items(user_id=user_id)
            if all_items and cache_service is not None:
                await asyncio.to_thread(
                    cache_service.set_personalized_feed,
                    cache_user_key,
                    [item.model_dump() for item in all_items],
                    ttl_seconds=300,  # 5분 캐시
                )

        total_elements = len(all_items)
        total_pages = (total_elements + size - 1) // size if total_elements > 0 else 0
        start_idx = page * size
        end_idx = start_idx + size
        page_content = all_items[start_idx:end_idx] if start_idx < total_elements else []
        has_next = (page < total_pages - 1) if total_pages > 0 else False

        return PersonalizedPageResponse(
            content=page_content,
            page=page,
            size=size,
            totalElements=total_elements,
            totalPages=total_pages,
            hasNext=has_next,
        )

