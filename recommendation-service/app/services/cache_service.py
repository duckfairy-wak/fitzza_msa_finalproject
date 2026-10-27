import hashlib
import json
import logging
from typing import Any, Optional

from app.clients.redis_client import RedisClient
from app.core.config import Settings

logger = logging.getLogger(__name__)


class CacheService:
    """추천 및 검색 도메인 전용 캐싱 서비스."""

    def __init__(self, redis_client: RedisClient, settings: Settings) -> None:
        self.redis = redis_client
        self.settings = settings
        # 임베딩 벡터 등 정적 데이터는 더 긴 TTL(기본 24시간) 적용 가능
        self.embedding_ttl = int(getattr(settings, "redis_ttl_seconds", 3600) * 24)

    @staticmethod
    def _hash_string(content: str) -> str:
        return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()

    @staticmethod
    def _hash_dict(data: dict[str, Any]) -> str:
        canonical_json = json.dumps(data, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()

    # 1. 파이프라인 추천 결과 캐시
    def get_pipeline_result(
        self,
        user_query: str,
        user_id: str,
    ) -> Optional[dict[str, Any]]:
        query_hash = self._hash_string(user_query)
        cache_key = f"pipeline:{user_id}:{query_hash}"
        cached = self.redis.get(cache_key)
        if cached is not None:
            logger.info("파이프라인 캐시 적중 (userId=%s, key=%s)", user_id, cache_key)
            return cached
        return None

    def set_pipeline_result(
        self,
        user_query: str,
        user_id: str,
        result: dict[str, Any],
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        query_hash = self._hash_string(user_query)
        cache_key = f"pipeline:{user_id}:{query_hash}"
        return self.redis.set(cache_key, result, ttl_seconds=ttl_seconds)

    # 2. Fashion-CLIP 텍스트 임베딩 벡터 캐시
    def get_text_embedding(self, clip_query_en: str) -> Optional[list[float]]:
        query_hash = self._hash_string(clip_query_en.lower())
        cache_key = f"embed:{query_hash}"
        cached = self.redis.get(cache_key)
        if isinstance(cached, list):
            logger.debug("텍스트 임베딩 캐시 적중: %s", clip_query_en)
            return cached
        return None

    def set_text_embedding(
        self,
        clip_query_en: str,
        vector: list[float],
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        query_hash = self._hash_string(clip_query_en.lower())
        cache_key = f"embed:{query_hash}"
        ttl = ttl_seconds if ttl_seconds is not None else self.embedding_ttl
        return self.redis.set(cache_key, vector, ttl_seconds=ttl)

    # 2-1. Fashion-CLIP 이미지 임베딩 벡터 캐시
    def get_image_embedding(self, image_hash: str) -> Optional[list[float]]:
        cache_key = f"embed:img:{image_hash}"
        cached = self.redis.get(cache_key)
        if isinstance(cached, list):
            logger.debug("이미지 임베딩 캐시 적중: %s", image_hash)
            return cached
        return None

    def set_image_embedding(
        self,
        image_hash: str,
        vector: list[float],
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        cache_key = f"embed:img:{image_hash}"
        ttl = ttl_seconds if ttl_seconds is not None else self.embedding_ttl
        return self.redis.set(cache_key, vector, ttl_seconds=ttl)

    # 3. Qdrant 벡터 검색 결과 캐시
    def get_search_result(
        self,
        search_params: dict[str, Any],
    ) -> Optional[list[dict[str, Any]]]:
        params_hash = self._hash_dict(search_params)
        cache_key = f"search:{params_hash}"
        cached = self.redis.get(cache_key)
        if isinstance(cached, list):
            logger.debug("검색 엔진 캐시 적중 (params_hash=%s)", params_hash)
            return cached
        return None

    def set_search_result(
        self,
        search_params: dict[str, Any],
        results: list[dict[str, Any]],
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        params_hash = self._hash_dict(search_params)
        cache_key = f"search:{params_hash}"
        return self.redis.set(cache_key, results, ttl_seconds=ttl_seconds)

    # 4. 코디 조합(Combo) 캐시
    def get_combo(self, combo_id: int) -> Optional[dict[str, Any]]:
        cache_key = f"combo:{combo_id}"
        cached = self.redis.get(cache_key)
        if isinstance(cached, dict):
            logger.debug("코디 조합 캐시 적중 (comboId=%d)", combo_id)
            return cached
        return None

    def set_combo(
        self,
        combo_id: int,
        combo_data: dict[str, Any],
        ttl_seconds: Optional[int] = None,
    ) -> bool:
        cache_key = f"combo:{combo_id}"
        return self.redis.set(cache_key, combo_data, ttl_seconds=ttl_seconds)

    def invalidate_combo(self, combo_id: int) -> bool:
        cache_key = f"combo:{combo_id}"
        return self.redis.delete(cache_key)

    def invalidate_user_pipeline(self, user_id: str) -> int:
        pattern = f"pipeline:{user_id}:*"
        return self.redis.delete_pattern(pattern)

    # 5. 홈 개인화 추천 피드 캐시
    PERSONALIZED_FEED_TTL = 300  # 5분 (300초)

    def get_personalized_feed(
        self, user_id: int | str
    ) -> Optional[list[dict[str, Any]]]:
        """캐시된 80개 개인화 피드 상품 딕셔너리 목록을 조회한다."""
        cache_key = f"feed:{user_id}"
        cached = self.redis.get(cache_key)
        if isinstance(cached, list):
            logger.info("개인화 피드 캐시 적중 (userId=%s, items=%d)", user_id, len(cached))
            return cached
        return None

    def set_personalized_feed(
        self,
        user_id: int | str,
        items: list[dict[str, Any]],
        ttl_seconds: int = PERSONALIZED_FEED_TTL,
    ) -> bool:
        """80개 개인화 피드 상품 목록을 Redis에 5분(300초)간 캐싱한다."""
        cache_key = f"feed:{user_id}"
        return self.redis.set(cache_key, items, ttl_seconds=ttl_seconds)

    def delete_personalized_feed(self, user_id: int | str) -> bool:
        """개인화 피드 캐시를 수동 무효화한다 (새로고침 시)."""
        cache_key = f"feed:{user_id}"
        return self.redis.delete(cache_key)

