import hashlib
import io
import logging
import os
from typing import Any, Optional

from PIL import Image
import torch
from dotenv import load_dotenv
from transformers import CLIPModel, CLIPProcessor
from qdrant_client import QdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)

load_dotenv()


class FashionSearchEngine:
    # 초기 실험용 가중치. 검색 평가 결과에 따라 조정할 것.
    VECTOR_WEIGHT = 0.75
    ATTRIBUTE_WEIGHT = 0.3

    # 기존 기준 유지. 실제 검색 결과로 적절성을 검증할 것.
    MIN_SIMILARITY = 0.2

    # Fashion-CLIP Zero-Shot 5대 대분류 프롬프트
    CATEGORY_PROMPTS: dict[str, str] = {
        "상의": "a photo of a top, t-shirt, shirt, knit, blouse, hoodie, sweatshirt",
        "아우터": "a photo of outerwear, jacket, coat, blazer, padding, cardigan",
        "하의": "a photo of pants, jeans, trousers, shorts, skirt, slacks",
        "신발": "a photo of shoes, sneakers, boots, loafers, sandals",
        "모자": "a photo of a hat, cap, beanie, beret",
    }

    # Fashion-CLIP Zero-Shot 표준 색상 프롬프트 (무신사 color_normalized 16종 기준)
    COLOR_PROMPTS: dict[str, str] = {
        "black": "a photo of black clothing",
        "white": "a photo of white clothing",
        "gray": "a photo of gray clothing",
        "charcoal": "a photo of dark charcoal clothing",
        "navy": "a photo of navy blue clothing",
        "blue": "a photo of blue clothing",
        "beige": "a photo of beige clothing",
        "ivory": "a photo of ivory or cream clothing",
        "brown": "a photo of brown clothing",
        "khaki": "a photo of khaki clothing",
        "green": "a photo of green clothing",
        "red": "a photo of red clothing",
        "orange": "a photo of orange clothing",
        "purple": "a photo of purple clothing",
        "pink": "a photo of pink clothing",
        "yellow": "a photo of yellow clothing",
    }

    # 유사 색상 클러스터 (인접 색상 보조 보너스용)
    COLOR_SIMILARITY_GROUPS: dict[str, set[str]] = {
        "black": {"black", "charcoal"},
        "charcoal": {"charcoal", "black", "gray"},
        "gray": {"gray", "charcoal", "black"},
        "white": {"white", "ivory"},
        "ivory": {"ivory", "white", "beige"},
        "beige": {"beige", "ivory", "brown"},
        "brown": {"brown", "beige", "khaki"},
        "navy": {"navy", "blue"},
        "blue": {"blue", "navy"},
        "khaki": {"khaki", "green", "brown"},
        "green": {"green", "khaki"},
    }

    COLOR_EXACT_BOOST = 0.15
    COLOR_SIMILAR_BOOST = 0.08

    def __init__(
            self,
            qdrant_url: Optional[str] = None,
            collection_name: Optional[str] = None,
            model_name: str = "patrickjohncyh/fashion-clip",
            cache_service: Optional[Any] = None,
    ):
        self.cache_service = cache_service
        self.qdrant_url = (
                qdrant_url
                or os.getenv("QDRANT_URL", "http://localhost:6333")
        )
        self.collection_name = (
                collection_name
                or os.getenv("QDRANT_COLLECTION_NAME", "musinsa_products")
        )

        self.client = QdrantClient(url=self.qdrant_url)

        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # 1. Fashion-CLIP 모델 로드 (로컬 캐시 우선 시도 -> 실패 시 원격 허브 다운로드)
        try:
            self.model = CLIPModel.from_pretrained(
                model_name, local_files_only=True
            )
            logger.info("Fashion-CLIP 모델 로컬 캐시에서 로드 완료: %s", model_name)
        except Exception:
            logger.info(
                "Fashion-CLIP 모델 로컬 캐시가 없어 원격 허브에서 다운로드를 진행합니다: %s",
                model_name,
            )
            self.model = CLIPModel.from_pretrained(
                model_name, local_files_only=False
            )
        self.model.to(self.device)

        # 2. Fashion-CLIP 프로세서 로드 (로컬 캐시 우선 시도 -> 실패 시 원격 허브 다운로드)
        try:
            self.processor = CLIPProcessor.from_pretrained(
                model_name, local_files_only=True
            )
            logger.info("Fashion-CLIP 프로세서 로컬 캐시에서 로드 완료: %s", model_name)
        except Exception:
            logger.info(
                "Fashion-CLIP 프로세서 로컬 캐시가 없어 원격 허브에서 다운로드를 진행합니다: %s",
                model_name,
            )
            self.processor = CLIPProcessor.from_pretrained(
                model_name, local_files_only=False
            )
        self.model.eval()
        self._category_vectors: dict[str, list[float]] = {}
        self._color_vectors: dict[str, list[float]] = {}

    def _normalize(self, tensor: torch.Tensor) -> torch.Tensor:
        """임베딩 벡터 L2 정규화."""
        return tensor / tensor.norm(
            p=2, dim=-1, keepdim=True
        ).clamp_min(1e-12)

    def encode_text(self, clip_query_en: str) -> list[float]:
        """검색 텍스트를 Fashion-CLIP 벡터로 변환."""
        if self.cache_service is not None:
            cached_vector = self.cache_service.get_text_embedding(clip_query_en)
            if cached_vector is not None:
                return cached_vector

        inputs = self.processor(
            text=[clip_query_en],
            return_tensors="pt",
            padding=True,
        ).to(self.device)

        with torch.no_grad():
            feats = self.model.get_text_features(**inputs)

            if (
                    hasattr(feats, "pooler_output")
                    and feats.pooler_output is not None
            ):
                feats = feats.pooler_output
            elif hasattr(feats, "last_hidden_state"):
                feats = feats.last_hidden_state[:, 0, :]

            feats = self._normalize(feats)

        vector = feats.cpu().numpy()[0].tolist()
        if self.cache_service is not None:
            self.cache_service.set_text_embedding(clip_query_en, vector)
        return vector

    def encode_image(self, image_input: bytes | Image.Image) -> list[float]:
        """검색 이미지를 Fashion-CLIP 벡터(512차원)로 변환."""
        image_hash: Optional[str] = None
        if isinstance(image_input, bytes):
            image_hash = hashlib.sha256(image_input).hexdigest()
            if self.cache_service is not None:
                cached_vector = self.cache_service.get_image_embedding(image_hash)
                if cached_vector is not None:
                    return cached_vector
            image = Image.open(io.BytesIO(image_input)).convert("RGB")
        elif isinstance(image_input, Image.Image):
            image = image_input.convert("RGB")
        else:
            raise ValueError("image_input은 bytes 또는 PIL.Image.Image 객체여야 합니다.")

        inputs = self.processor(
            images=[image],
            return_tensors="pt",
        ).to(self.device)

        with torch.no_grad():
            feats = self.model.get_image_features(**inputs)

            if (
                hasattr(feats, "pooler_output")
                and feats.pooler_output is not None
            ):
                feats = feats.pooler_output
            elif hasattr(feats, "last_hidden_state"):
                feats = feats.last_hidden_state[:, 0, :]

            feats = self._normalize(feats)

        vector = feats.cpu().numpy()[0].tolist()
        if image_hash and self.cache_service is not None:
            self.cache_service.set_image_embedding(image_hash, vector)
        return vector

    def _get_category_vectors(self) -> dict[str, list[float]]:
        """5대 카테고리(상의, 아우터, 하의, 신발, 모자) 텍스트 임베딩 벡터를 지연 초기화하여 반환."""
        if not self._category_vectors:
            for cat, prompt in self.CATEGORY_PROMPTS.items():
                self._category_vectors[cat] = self.encode_text(prompt)
        return self._category_vectors

    def classify_category(self, image_vector: list[float]) -> tuple[str, float]:
        """이미지 벡터로부터 가장 유사한 상위 카테고리(상의, 아우터, 하의, 신발, 모자)와 신뢰도 점수를 Zero-Shot으로 자동 판별."""
        cat_vectors = self._get_category_vectors()
        best_cat = "상의"
        highest_score = -1.0
        for cat_name, cat_vec in cat_vectors.items():
            # L2 정규화된 벡터 간의 내적은 코사인 유사도와 동일함
            score = float(sum(a * b for a, b in zip(image_vector, cat_vec)))
            if score > highest_score:
                highest_score = score
                best_cat = cat_name
        return best_cat, round(highest_score, 4)

    def _get_color_vectors(self) -> dict[str, list[float]]:
        """16대 표준 색상 텍스트 임베딩 벡터를 지연 초기화하여 반환."""
        if not self._color_vectors:
            for color_name, prompt in self.COLOR_PROMPTS.items():
                self._color_vectors[color_name] = self.encode_text(prompt)
        return self._color_vectors

    def classify_color(self, image_vector: list[float]) -> tuple[str, float]:
        """이미지 벡터로부터 가장 유사한 대표 색상(black, white, navy 등)과 신뢰도 점수를 Zero-Shot으로 자동 판별."""
        color_vectors = self._get_color_vectors()
        best_color = "black"
        highest_score = -1.0
        for color_name, color_vec in color_vectors.items():
            score = float(sum(a * b for a, b in zip(image_vector, color_vec)))
            if score > highest_score:
                highest_score = score
                best_color = color_name
        return best_color, round(highest_score, 4)


    @staticmethod
    def _as_list(value: Any) -> list[str]:
        """payload의 단일 값 또는 배열을 문자열 배열로 변환."""
        if value is None:
            return []

        if isinstance(value, list):
            return [
                str(item).strip()
                for item in value
                if item is not None and str(item).strip()
            ]

        if isinstance(value, str) and value.strip():
            return [value.strip()]

        return []

    @staticmethod
    def _first_feature_value(
            features: dict[str, Any],
            key: str,
    ) -> Optional[str]:
        """features에서 첫 번째 유효한 특성값을 가져온다."""
        values = FashionSearchEngine._as_list(features.get(key))
        return values[0] if values else None

    def _calculate_attribute_score(
            self,
            payload: dict[str, Any],
            season_preferences: list[str] | None,
            fit_type: str | None,
            touch_type: str | None,
            stretch_type: str | None,
            transparency_type: str | None,
            thickness_type: str | None,
    ) -> float:
        """
        사용자가 요청한 상품 특성의 일치 비율을 계산한다.
        특성 데이터가 없으면 해당 특성은 불일치로 계산한다.
        계절은 season_candidates만 사용한다.
        """
        features = payload.get("features") or {}

        if not isinstance(features, dict):
            features = {}

        total = 0
        matched = 0

        feature_preferences = {
            "핏": fit_type,
            "촉감": touch_type,
            "신축성": stretch_type,
            "비침": transparency_type,
            "두께": thickness_type,
        }

        for feature_key, requested_value in feature_preferences.items():
            if requested_value is None:
                continue

            total += 1
            product_value = self._first_feature_value(
                features, feature_key
            )

            if product_value == requested_value:
                matched += 1

        if season_preferences:
            total += 1

            product_seasons = set(
                self._as_list(payload.get("season_candidates"))
            )

            if product_seasons.intersection(season_preferences):
                matched += 1

        # 특성 조건이 없으면 벡터 유사도만 사용한다.
        if total == 0:
            return 0.0

        return matched / total

    def search(
            self,
            clip_query_en: str,
            category: str | None = None,
            subcategory: str | None = None,
            season_preferences: list[str] | None = None,
            slot_budget: int | None = None,
            max_price: int | None = None,
            color: str | None = None,
            fit_type: str | None = None,
            touch_type: str | None = None,
            stretch_type: str | None = None,
            transparency_type: str | None = None,
            thickness_type: str | None = None,
            top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Qdrant 검색 후 필수 조건 검사 및 특성 기반 재정렬."""
        if not clip_query_en or not clip_query_en.strip():
            raise ValueError("clip_query_en은 비어 있을 수 없습니다.")

        if top_k < 1:
            raise ValueError("top_k는 1 이상이어야 합니다.")

        if max_price is not None and max_price <= 0:
            raise ValueError("max_price는 0보다 커야 합니다.")

        if slot_budget is not None and slot_budget <= 0:
            raise ValueError("slot_budget은 0보다 커야 합니다.")

        cache_params = {
            "clip_query_en": clip_query_en,
            "category": category,
            "subcategory": subcategory,
            "season_preferences": season_preferences,
            "slot_budget": slot_budget,
            "max_price": max_price,
            "color": color,
            "fit_type": fit_type,
            "touch_type": touch_type,
            "stretch_type": stretch_type,
            "transparency_type": transparency_type,
            "thickness_type": thickness_type,
            "top_k": top_k,
        }
        if self.cache_service is not None:
            cached_results = self.cache_service.get_search_result(cache_params)
            if cached_results is not None:
                return cached_results

        query_vector = self.encode_text(clip_query_en)
        top_results = self._query_and_rank_points(
            query_vector=query_vector,
            category=category,
            subcategory=subcategory,
            season_preferences=season_preferences,
            slot_budget=slot_budget,
            max_price=max_price,
            color=color,
            fit_type=fit_type,
            touch_type=touch_type,
            stretch_type=stretch_type,
            transparency_type=transparency_type,
            thickness_type=thickness_type,
            top_k=top_k,
        )

        if self.cache_service is not None:
            self.cache_service.set_search_result(cache_params, top_results)

        return top_results

    MIN_VISUAL_SIMILARITY = 0.75
    MAX_VISUAL_SEARCH_RESULTS: Optional[int] = None

    def search_by_image(
        self,
        image_input: bytes | Image.Image,
        min_similarity: float = 0.75,
        max_limit: Optional[int] = None,
        color_boost: float = 0.15,
    ) -> tuple[str, str, list[dict[str, Any]]]:
        """순수 의류 이미지 기반 Fashion-CLIP 시각적 유사 상품 검색 (카테고리 선분류 + 색상 부스팅 + 유사도 0.75 이상 컷오프)."""
        image_hash: Optional[str] = (
            hashlib.sha256(image_input).hexdigest()
            if isinstance(image_input, bytes)
            else None
        )

        query_vector = self.encode_image(image_input)
        detected_category, cat_confidence = self.classify_category(query_vector)
        detected_color, color_confidence = self.classify_color(query_vector)
        logger.info(
            "Fashion-CLIP 자동 분류 결과: 카테고리=%s (신뢰도: %.4f), 색상=%s (신뢰도: %.4f)",
            detected_category,
            cat_confidence,
            detected_color,
            color_confidence,
        )

        cache_params = {
            "image_hash": image_hash,
            "min_similarity": min_similarity,
            "max_limit": max_limit,
            "color_boost": color_boost,
            "detected_category": detected_category,
            "detected_color": detected_color,
        }
        if image_hash and self.cache_service is not None:
            cached_results = self.cache_service.get_search_result(cache_params)
            if cached_results is not None:
                return detected_category, detected_color, cached_results

        # 선분류된 대분류(상의, 아우터, 하의, 신발, 모자) 카테고리 필터 자동 적용
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="category",
                    match=models.MatchValue(value=detected_category),
                )
            ]
        )

        # 갯수 제한 없이 유사도 0.75 이상을 모두 추출 (색상 부스팅 고려하여 하한선 설정)
        # 참고: max_limit이 None일 때 5,000개 상한(fetch_limit)은 카탈로그 상품(3,000개)의 색상 매핑 포인트를 단일 카테고리 내에서 누락 없이 전수 커버하는 안전 상한선(Safety Ceiling)입니다.
        fetch_limit = (max_limit * 3) if max_limit is not None else 5000
        score_threshold = max(0.0, min_similarity - color_boost)
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=query_filter,
            score_threshold=score_threshold,
            limit=fetch_limit,
            with_payload=True,
            with_vectors=False,
        )

        similar_colors = self.COLOR_SIMILARITY_GROUPS.get(detected_color, set())

        results: list[dict[str, Any]] = []
        for hit in response.points:
            vector_score = float(hit.score)
            payload = hit.payload or {}
            product_colors = self._as_list(payload.get("color_normalized"))
            product_color_set = {c.lower() for c in product_colors}

            # 색상 일치 여부에 따른 보너스 가중치 계산 (동일 색상 +0.15, 인접 색상 +0.08)
            boost = 0.0
            if detected_color in product_color_set:
                boost = color_boost
            elif product_color_set.intersection(similar_colors):
                boost = self.COLOR_SIMILAR_BOOST

            final_score = min(1.0, round(vector_score + boost, 4))
            if final_score < min_similarity:
                continue

            results.append(
                {
                    "similarity_score": final_score,
                    "product_id": payload.get("product_id"),
                    "product_name": payload.get("product_name"),
                    "brand_name": payload.get("brand_name"),
                    "category": payload.get("category"),
                    "subcategory": payload.get("subcategory"),
                    "price": payload.get("price") or 0,
                    "color_raw": payload.get("color_raw"),
                    "color_normalized": product_colors,
                    "image_url": payload.get("image_url"),
                    "product_url": payload.get("product_url"),
                }
            )

        results.sort(
            key=lambda item: item["similarity_score"],
            reverse=True,
        )
        top_results = results[:max_limit] if max_limit is not None else results

        if image_hash and self.cache_service is not None:
            self.cache_service.set_search_result(cache_params, top_results)

        return detected_category, detected_color, top_results

    def _query_and_rank_points(
        self,
        query_vector: list[float],
        category: str | None = None,
        subcategory: str | None = None,
        season_preferences: list[str] | None = None,
        slot_budget: int | None = None,
        max_price: int | None = None,
        color: str | None = None,
        fit_type: str | None = None,
        touch_type: str | None = None,
        stretch_type: str | None = None,
        transparency_type: str | None = None,
        thickness_type: str | None = None,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        category_map = {
            "top": "상의",
            "outer": "아우터",
            "bottom": "하의",
            "shoes": "신발",
            "hat": "모자",
        }
        db_category = (
            category_map.get(category, category)
            if category
            else None
        )

        # 1. 반드시 지켜야 하는 검색 조건 (Hard Filtering)
        must_conditions = []

        if db_category is not None:
            must_conditions.append(
                models.FieldCondition(
                    key="category",
                    match=models.MatchValue(value=db_category),
                )
            )

        if subcategory:
            must_conditions.append(
                models.FieldCondition(
                    key="subcategory",
                    match=models.MatchValue(value=subcategory),
                )
            )

        # color는 표준화된 값이어야 한다. 예: black, gray
        if color:
            must_conditions.append(
                models.FieldCondition(
                    key="color_normalized",
                    match=models.MatchValue(value=color),
                )
            )

        # max_price는 검색에서 허용할 최대 가격이다.
        if max_price is not None:
            must_conditions.append(
                models.FieldCondition(
                    key="price",
                    range=models.Range(lte=max_price),
                )
            )

        query_filter = models.Filter(
            must=must_conditions or None,
        )

        # 2. 후보 조회: 우선 top_k * 5개 유지
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=query_vector,
            query_filter=query_filter,
            limit=top_k * 5,
            with_payload=True,
            with_vectors=True,
        )

        results: list[dict[str, Any]] = []

        for hit in response.points:
            vector_score = float(hit.score)

            if vector_score < self.MIN_SIMILARITY:
                continue

            payload = hit.payload or {}

            product_colors = self._as_list(
                payload.get("color_normalized")
            )

            raw_color = payload.get("color_raw")
            product_subcategory = payload.get("subcategory")

            # 방어적 검사 1: 지정 색상과 다르면 제외
            if color and color not in product_colors:
                continue

            # 방어적 검사 2: 서브카테고리가 명시되었는데 페이로드와 다르면 제외
            if subcategory and product_subcategory != subcategory:
                continue

            # 3. 상품 특성 일치도
            attribute_score = self._calculate_attribute_score(
                payload=payload,
                season_preferences=season_preferences,
                fit_type=fit_type,
                touch_type=touch_type,
                stretch_type=stretch_type,
                transparency_type=transparency_type,
                thickness_type=thickness_type,
            )

            # 4. 벡터 유사도와 상품 특성 점수를 결합
            if any([
                season_preferences,
                fit_type,
                touch_type,
                stretch_type,
                transparency_type,
                thickness_type,
            ]):
                composite_score = (
                    self.VECTOR_WEIGHT * vector_score
                    + self.ATTRIBUTE_WEIGHT * attribute_score
                )
            else:
                composite_score = vector_score

            # 5. slot_budget 초과 상품은 점수 감점
            actual_price = payload.get("price")

            if (
                slot_budget is not None
                and actual_price is not None
                and slot_budget > 0
                and actual_price > slot_budget
            ):
                over_ratio = (
                    actual_price - slot_budget
                ) / slot_budget

                composite_score -= over_ratio * 0.1

            results.append(
                {
                    "final_score": composite_score,
                    "composite_score": composite_score,
                    "similarity_score": round(vector_score, 4),
                    "attribute_score": round(attribute_score, 4),
                    "product_id": payload.get("product_id"),
                    "product_name": payload.get("product_name"),
                    "brand_name": payload.get("brand_name"),
                    "category": payload.get("category"),
                    "subcategory": product_subcategory,
                    "price": actual_price,
                    "color_raw": raw_color,
                    "color_normalized": product_colors,
                    "season_candidates": payload.get(
                        "season_candidates"
                    ) or [],
                    "features": payload.get("features") or {},
                    "sizes": payload.get("sizes") or [],
                    "image_url": payload.get("image_url"),
                    "product_url": payload.get("product_url"),
                    "vector": hit.vector,
                }
            )

        results.sort(
            key=lambda item: item["composite_score"],
            reverse=True,
        )

        return results[:top_k]

