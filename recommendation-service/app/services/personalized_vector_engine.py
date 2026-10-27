from __future__ import annotations

import json
import logging
import math
import os
from typing import Any, Optional

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.core.config import get_settings
from app.services.user_history_service import UserActionHistory

logger = logging.getLogger(__name__)


def _l2_normalize(vector: np.ndarray) -> np.ndarray:
    """벡터를 L2 정규화한다. 영벡터일 경우 최소 엡실론으로 나눈다."""
    norm = np.linalg.norm(vector)
    if norm < 1e-12:
        return vector
    return vector / norm


class PersonalizedVectorEngine:
    """
    사용자의 행동 이력(이상형 월드컵 1등, 찜/장바구니, 최근 구매 5건)을 기반으로
    취향 벡터를 합성하고, 이력이 없거나 부족한 경우 Cold-Start 기본 벡터로 폴백하는 엔진.
    """

    DEFAULT_COLD_START_PROMPT = "clean minimal daily basic casual fashion outfit"

    # 기본 가중치 비율 (총합 1.0)
    WORLDCUP_WEIGHT = 0.5
    INTEREST_WEIGHT = 0.3  # 찜(wishlist) + 장바구니(cart)
    PURCHASE_WEIGHT = 0.2  # 최근 5건 구매(purchases)

    VECTOR_DIM = 512

    def __init__(
        self,
        qdrant_client: Optional[QdrantClient] = None,
        collection_name: Optional[str] = None,
        search_engine: Optional[Any] = None,
        qdrant_url: Optional[str] = None,
        cold_start_path: Optional[str] = None,
    ) -> None:
        settings = get_settings()
        self.collection_name = (
            collection_name or settings.qdrant_collection_name or "musinsa_products"
        )
        self.search_engine = search_engine

        if cold_start_path is not None:
            self.cold_start_path: Optional[str] = cold_start_path
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            default_path = os.path.abspath(
                os.path.join(base_dir, "../../data/cold_start_vector.json")
            )
            self.cold_start_path = default_path if os.path.exists(default_path) else None

        if qdrant_client is not None:
            self.client = qdrant_client
        else:
            url = qdrant_url or settings.qdrant_url or "http://localhost:6333"
            self.client = QdrantClient(url=url)

        self._cold_start_vector_cache: Optional[list[float]] = None

    def get_cold_start_vector(self) -> list[float]:
        """
        이력이 없는 신규 유저 또는 게스트를 위한 기본 Cold-Start 베이직 룩 벡터 반환.
        1) cold_start_path 파일이 존재하면 사전 계산된 512차원 벡터를 즉시 로드하여 반환.
        2) 파일이 없고 search_engine이 주어져 있으면 베이직 프롬프트를 동적 인코딩.
        3) 모두 실패 시 결정론적인 단위 벡터(L2 norm 1.0) 생성 반환.
        """
        if self._cold_start_vector_cache is not None:
            return self._cold_start_vector_cache

        # 1) 사전 계산된 Cold-Start 벡터 파일 로드 시도
        if self.cold_start_path and os.path.exists(self.cold_start_path):
            try:
                with open(self.cold_start_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                vec = data.get("vector")
                if isinstance(vec, list) and len(vec) == self.VECTOR_DIM:
                    norm_vec = _l2_normalize(np.array(vec, dtype=np.float32)).tolist()
                    self._cold_start_vector_cache = norm_vec
                    return norm_vec
            except Exception as e:
                logger.warning("사전 계산된 Cold-Start 벡터 파일 로드 실패: %s", e)

        # 2) SearchEngine의 CLIP 인코더 활용 시도
        if self.search_engine is not None and hasattr(self.search_engine, "encode_text"):
            try:
                encoded = self.search_engine.encode_text(self.DEFAULT_COLD_START_PROMPT)
                if isinstance(encoded, list) and len(encoded) == self.VECTOR_DIM:
                    norm_vec = _l2_normalize(np.array(encoded, dtype=np.float32)).tolist()
                    self._cold_start_vector_cache = norm_vec
                    return norm_vec
            except Exception as e:
                logger.warning("Cold-Start 프롬프트 인코딩 실패, 기본 상수 벡터 사용: %s", e)

        # 3) 결정론적 512차원 기본 정규화 벡터 (테스트 및 독립 실행용)
        # 1/sqrt(512) 값으로 채워진 L2 Norm = 1.0 벡터 생성
        val = 1.0 / math.sqrt(self.VECTOR_DIM)
        deterministic_vec = [val] * self.VECTOR_DIM
        self._cold_start_vector_cache = deterministic_vec
        return deterministic_vec

    def fetch_product_vectors(
        self, product_ids: list[int] | set[int]
    ) -> dict[int, list[float]]:
        """
        Qdrant 컬렉션에서 주어진 productId 목록에 해당하는 벡터들을 일괄 조회한다.
        MatchAny 필터를 통해 1회의 Qdrant scroll 호출로 수집.
        """
        clean_ids = [int(pid) for pid in product_ids if pid is not None and int(pid) > 0]
        if not clean_ids:
            return {}

        try:
            scroll_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="product_id",
                        match=models.MatchAny(any=clean_ids),
                    )
                ]
            )
            # 색상별로 동일 상품 ID에 대한 point가 복수 개 존재할 수 있으므로 모든 페이지를 순회 조회
            points = []
            offset = None
            while True:
                batch, offset = self.client.scroll(
                    collection_name=self.collection_name,
                    scroll_filter=scroll_filter,
                    with_vectors=True,
                    limit=max(len(clean_ids) * 4, 64),
                    offset=offset,
                )
                points.extend(batch)
                if offset is None:
                    break

            result_map: dict[int, list[float]] = {}
            for point in points:
                if not point.vector or not point.payload:
                    continue
                pid_val = point.payload.get("product_id")
                if pid_val is None:
                    continue
                try:
                    pid = int(pid_val)
                except (ValueError, TypeError):
                    continue

                # 첫 번째 벡터 저장 (동일 상품 복수 이미지 중 대표 1건)
                if pid not in result_map:
                    raw_vec = point.vector
                    if isinstance(raw_vec, list):
                        result_map[pid] = raw_vec
                    elif hasattr(raw_vec, "tolist"):
                        result_map[pid] = raw_vec.tolist()

            return result_map
        except Exception as e:
            logger.error("Qdrant 상품 벡터 일괄 조회 실패: %s", e)
            return {}

    def synthesize_user_taste_vector(
        self,
        history: UserActionHistory,
        vector_map: dict[int, list[float]],
    ) -> list[float]:
        """
        수집된 사용자 이력과 Qdrant 상품 벡터 맵을 기반으로 취향 합성 벡터를 계산한다.

        가중치 정책:
        - 월드컵 1등 상품: 0.5
        - 찜 + 장바구니 상품 평균: 0.3
        - 최근 구매 상품(5건) 평균: 0.2
        * 일부 이력이 없는 경우, 존재하는 이력들의 가중치를 비율에 맞게 동적 재조정(Dynamic Re-weighting)
        * 유효한 벡터가 단 하나도 없으면 Cold-Start 벡터 반환
        """
        # 1. 월드컵 1등 상품 벡터
        wc_vec: Optional[np.ndarray] = None
        if (
            history.worldcup_winner_id is not None
            and history.worldcup_winner_id in vector_map
        ):
            wc_vec = _l2_normalize(
                np.array(vector_map[history.worldcup_winner_id], dtype=np.float32)
            )

        # 2. 관심(찜 + 장바구니) 상품 벡터 평균
        interest_pids = set(history.wishlist_product_ids) | set(history.cart_product_ids)
        interest_vectors: list[np.ndarray] = [
            _l2_normalize(np.array(vector_map[pid], dtype=np.float32))
            for pid in interest_pids
            if pid in vector_map
        ]
        interest_vec: Optional[np.ndarray] = None
        if interest_vectors:
            interest_vec = _l2_normalize(np.mean(interest_vectors, axis=0))

        # 3. 구매(최근 5건) 상품 벡터 평균
        purchase_pids = set(history.purchased_product_ids)
        purchase_vectors: list[np.ndarray] = [
            _l2_normalize(np.array(vector_map[pid], dtype=np.float32))
            for pid in purchase_pids
            if pid in vector_map
        ]
        purchase_vec: Optional[np.ndarray] = None
        if purchase_vectors:
            purchase_vec = _l2_normalize(np.mean(purchase_vectors, axis=0))

        # 4. 활성화된 그룹 체크 및 동적 가중치 재조정
        active_components: list[tuple[float, np.ndarray]] = []
        if wc_vec is not None:
            active_components.append((self.WORLDCUP_WEIGHT, wc_vec))
        if interest_vec is not None:
            active_components.append((self.INTEREST_WEIGHT, interest_vec))
        if purchase_vec is not None:
            active_components.append((self.PURCHASE_WEIGHT, purchase_vec))

        # 매칭된 벡터가 전무한 경우 Cold-Start로 폴백
        if not active_components:
            return self.get_cold_start_vector()

        total_weight = sum(w for w, _ in active_components)
        if total_weight <= 0:
            return self.get_cold_start_vector()

        # 5. 가중치 정규화 및 선형 결합
        composite_vector = np.zeros(self.VECTOR_DIM, dtype=np.float32)
        for raw_weight, vec in active_components:
            normalized_weight = raw_weight / total_weight
            composite_vector += normalized_weight * vec

        # 6. 최종 L2 정규화
        final_vector = _l2_normalize(composite_vector)
        return final_vector.tolist()

    def compute_user_taste_vector(self, history: UserActionHistory) -> list[float]:
        """
        이력 수집 결과를 바탕으로 Qdrant에서 벡터를 일괄 조회한 뒤 취향 벡터를 합성하여 반환한다.
        """
        if not history.has_any_history:
            return self.get_cold_start_vector()

        all_pids: set[int] = set()
        if history.worldcup_winner_id is not None:
            all_pids.add(history.worldcup_winner_id)
        all_pids.update(history.wishlist_product_ids)
        all_pids.update(history.cart_product_ids)
        all_pids.update(history.purchased_product_ids)

        vector_map = self.fetch_product_vectors(all_pids)
        return self.synthesize_user_taste_vector(history, vector_map)
