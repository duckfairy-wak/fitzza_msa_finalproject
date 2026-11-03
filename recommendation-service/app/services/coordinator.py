import logging
import time
from typing import Any, Optional
from app.services.query_parser import QueryParser, SlotQuery
from app.services.search_engine import FashionSearchEngine
from app.services.harmonizer import OutfitHarmonizer
from app.services.response_generator import ResponseGenerator
from app.services.size_resolver import SizeProfileResolver

logger = logging.getLogger(__name__)

# 자연어 의도 분석 -> 단품/코디 분기 -> 조화도 검수 -> 응답 생성하는 전체 흐름 총괄

class FashionPipelineCoordinator:
    def __init__(
        self,
        cache_service: Any = None,
        repository: Any = None,
        product_client: Any = None,
    ):
        """패션 추천 파이프라인의 파서, 검색 엔진, 사이즈 리졸버, 하모나이저, 응답 생성기를 초기화한다."""
        logger.info("패션 추천 파이프라인 컴포넌트 초기화 중...")
        self.cache_service = cache_service
        self.repository = repository
        self.product_client = product_client
        self.parser = QueryParser()
        self.engine = FashionSearchEngine(cache_service=cache_service)
        self.size_resolver = SizeProfileResolver()
        self.harmonizer = OutfitHarmonizer(self.engine)
        self.responder = ResponseGenerator()

        logger.info("전체 파이프라인 준비 완료")

    def _collect_latencies(self, total_duration: float) -> dict[str, Any]:
        """파이프라인 각 단계별 소요 시간 지표를 수집해 딕셔너리로 반환한다."""
        parser_build = getattr(self.parser, "last_prompt_build_latency", 0.0)
        parser_llm = getattr(self.parser, "last_latency", 0.0)

        search_clip = getattr(self.engine, "last_clip_latency", 0.0)
        search_qdrant = getattr(self.engine, "last_qdrant_latency", 0.0)
        search_scoring = getattr(self.engine, "last_scoring_latency", 0.0)
        search_url = getattr(self.engine, "last_url_latency", 0.0)

        size_resolve = getattr(self.size_resolver, "last_resolve_latency", 0.0)
        size_calc = getattr(self.size_resolver, "last_calc_latency", 0.0)
        size_total = getattr(self.size_resolver, "last_total_latency", 0.0)

        harm_combo = getattr(self.harmonizer, "last_combo_latency", 0.0)
        harm_s3 = getattr(self.harmonizer, "last_s3_latency", 0.0)
        harm_llm = getattr(self.harmonizer, "last_llm_latency", 0.0)
        harm_total = getattr(self.harmonizer, "last_total_latency", 0.0)

        resp_build = getattr(self.responder, "last_prompt_build_latency", 0.0)
        resp_llm = getattr(self.responder, "last_latency", 0.0)

        return {
            "query_parser": {
                "prompt_build": parser_build,
                "llm_api": parser_llm,
                "total": parser_build + parser_llm,
            },
            "search_engine": {
                "clip_embedding": search_clip,
                "qdrant_search": search_qdrant,
                "scoring_and_sort": search_scoring,
                "s3_presigned_url": search_url,
                "total": search_clip + search_qdrant + search_scoring + search_url,
            },
            "size_resolver": {
                "baseline_resolve": size_resolve,
                "size_calc": size_calc,
                "total": size_total,
            },
            "harmonizer": {
                "cartesian_and_vector": harm_combo,
                "s3_presigned_url": harm_s3,
                "vision_llm_api": harm_llm,
                "total": harm_total,
            },
            "response_generator": {
                "prompt_build": resp_build,
                "llm_api": resp_llm,
                "total": resp_build + resp_llm,
            },
            "total_pipeline": total_duration,
        }

    def _attach_size_info(
            self,
            items: list[dict[str, Any]],
            slot: SlotQuery,
            user_id: str,
            user_body: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """검색된 상품 후보군에 대해 SizeProfileResolver를 통해 최적 사이즈를 산출하고 부착한다.

        Args:
            items: Qdrant 벡터 검색을 통해 선정된 상품 후보군 목록.
            slot: 사용자의 검색 요청 슬롯 쿼리.
            user_id: 요청 사용자 ID.
            user_body: 사용자 신체 치수 프로필.

        Returns:
            각 상품에 추천 사이즈 및 산출 근거가 부착된 평가 결과 목록.
        """
        learned_pref: dict[str, float] | None = None
        if self.repository is not None and slot.subcategory:
            try:
                learned_pref = self.repository.get_user_size_preference(
                    user_id=user_id,
                    subcategory=slot.subcategory,
                )
            except Exception as exc:
                logger.warning(
                    "선호 실측 DB 조회 실패 (userId=%s, subcategory=%s): %s",
                    user_id,
                    slot.subcategory,
                    exc,
                )

        evaluated_items = []
        for item in items:
            size_result = self.size_resolver.resolve_and_calculate_size(
                user_id=user_id,
                subcategory=slot.subcategory,
                fit_type=slot.fit_type,
                candidate_products=[item],
                category_type=slot.category,
                user_body=user_body,
                learned_preference=learned_pref,
            )

            item["size_recommendation"] = size_result.get("recommendation")
            item["fit_source_type"] = size_result.get("source_type")
            evaluated_items.append(item)

        return evaluated_items

    def _search_slot_items(
            self,
            slot: SlotQuery,
            season_preferences: list[str],
            top_k: int,
    ) -> list[dict[str, Any]]:
        """
        QueryParser가 추출한 모든 검색 조건과 물성/예산 파라미터를 SearchEngine에 전달한다.
        """
        return self.engine.search(
            clip_query_en=slot.clip_query_en,
            category=slot.category,
            subcategory=slot.subcategory,
            season_preferences=season_preferences,
            slot_budget=slot.slot_budget,
            max_price=slot.max_price,
            color=slot.color,
            fit_type=slot.fit_type,
            touch_type=slot.touch_type,
            stretch_type=slot.stretch_type,
            transparency_type=slot.transparency_type,
            thickness_type=slot.thickness_type,
            top_k=top_k,
        )

    def run(self, user_query: str, user_id: str = "user_001", user_body: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """사용자 자연어 질의와 신체 정보를 받아 단품 또는 코디 추천 파이프라인을 실행한다."""
        pipeline_start = time.perf_counter()
        if hasattr(self.engine, "reset_latencies"):
            self.engine.reset_latencies()
        if hasattr(self.size_resolver, "reset_latencies"):
            self.size_resolver.reset_latencies()
        if hasattr(self.harmonizer, "reset_latencies"):
            self.harmonizer.reset_latencies()
        if hasattr(self.responder, "reset_latencies"):
            self.responder.reset_latencies()

        logger.info("파이프라인 실행 시작 (query=%s, user_id=%s)", user_query, user_id)

        # [1단계] LLM 질의 파싱
        intent = self.parser.parse(user_query)
        logger.info(
            "파서 결과: 의도=%s, 총예산=%s, 슬롯 수=%d개",
            intent.search_type,
            intent.total_budget,
            len(intent.slots),
        )

        logger.debug(
            "LLM 파싱 분석 결과: 의도=%s, 예산=%s, 계절=%s, TPO=%s, 슬롯수=%d",
            intent.search_type,
            intent.total_budget,
            intent.season_preferences,
            intent.tpo_summary,
            len(intent.slots),
        )

        for idx, slot in enumerate(intent.slots, 1):
            logger.debug(
                "[%d] 카테고리: %s / 서브: %s / 영문: %s / 예산: %s",
                idx,
                slot.category,
                slot.subcategory,
                slot.clip_query_en,
                slot.slot_budget,
            )

        # [2단계 - 단품 검색] 추출된 슬롯이 1개이거나 search_type이 single인 경우
        if not intent.slots and intent.search_type == "single":
            return {
                "type": "single",
                "query": user_query,
                "tpo": intent.tpo_summary,
                "intent": intent.model_dump() if hasattr(intent, "model_dump") else intent,
                "excluded_categories": [],
                "comment": "요청에서 검색할 상품을 찾지 못했습니다.",
                "results": [],
                "latencies": self._collect_latencies(time.perf_counter() - pipeline_start),
            }

        if intent.search_type == "single" or len(intent.slots) == 1:
            slot = intent.slots[0]
            items = self._search_slot_items(
                slot=slot,
                season_preferences=intent.season_preferences,
                top_k=9,
            )

            logger.info("검색 엔진 결과: 단품 후보 %d개 추출 완료", len(items))

            evaluated_items = self._attach_size_info(
                items=items,
                slot=slot,
                user_id=user_id,
                user_body=user_body,
            )

            comment = self.responder.generate_single_response(user_query, intent.tpo_summary, evaluated_items)
            total_prompt_tokens = (
                int(getattr(self.parser, "last_prompt_tokens", 0) or 0)
                + int(getattr(self.responder, "last_prompt_tokens", 0) or 0)
            )
            total_completion_tokens = (
                int(getattr(self.parser, "last_completion_tokens", 0) or 0)
                + int(getattr(self.responder, "last_completion_tokens", 0) or 0)
            )
            return {
                "type": "single",
                "query": user_query,
                "tpo": intent.tpo_summary,
                "intent": intent.model_dump() if hasattr(intent, "model_dump") else intent,
                "excluded_categories": [] if evaluated_items else [slot.category],
                "comment": comment,
                "results": evaluated_items,
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
                "latencies": self._collect_latencies(time.perf_counter() - pipeline_start),
            }

        # [2단계 - 코디 검색] 슬롯이 2개 이상 복합으로 들어온 경우
        slot_candidates: dict[str, list[dict[str, Any]]] = {}
        surviving_slots: list[SlotQuery] = []
        excluded_categories: list[str] = []

        for slot in intent.slots:
            items = self._search_slot_items(
                slot=slot,
                season_preferences=intent.season_preferences,
                top_k=5,
            )

            evaluated_slot_items = self._attach_size_info(
                items=items,
                slot=slot,
                user_id=user_id,
                user_body=user_body,
            )

            logger.info("검색 엔진 결과: 슬롯 '%s' -> %d개 후보 찾음", slot.category, len(evaluated_slot_items))

            if evaluated_slot_items:
                slot_candidates[slot.category] = evaluated_slot_items
                surviving_slots.append(slot)
            else:
                excluded_categories.append(slot.category)
                logger.info("슬롯 '%s'의 검색 결과가 0개이므로 코디 조합에서 제외하고 남은 슬롯으로 진행합니다.", slot.category)

        # 살아남은 카테고리가 1개 이하인 경우 (코디 조합 불가 -> outfits: [] 및 재검색 안내 반환)
        if len(slot_candidates) <= 1:
            logger.info(
                "검색 가능한 카테고리가 %d개뿐이어서 코디 조합을 구성할 수 없습니다. (제외된 카테고리: %s)",
                len(slot_candidates),
                excluded_categories,
            )
            return {
                "type": "coordination",
                "query": user_query,
                "tpo": intent.tpo_summary,
                "intent": intent.model_dump() if hasattr(intent, "model_dump") else intent,
                "excluded_categories": excluded_categories,
                "comment": "요청하신 조건에 맞는 추천 조합을 찾지 못했습니다. 검색 조건을 조금 완화해 다시 시도해주세요.",
                "outfits": [],
                "prompt_tokens": int(getattr(self.parser, "last_prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(self.parser, "last_completion_tokens", 0) or 0),
                "latencies": self._collect_latencies(time.perf_counter() - pipeline_start),
            }

        # 일부 슬롯이 제외된 경우, 살아남은 슬롯들의 slot_budget 합계를 반영해 유효 예산 산출
        effective_budget = intent.total_budget
        if intent.total_budget is not None and excluded_categories:
            surviving_budget_sum = sum(
                s.slot_budget for s in surviving_slots if s.slot_budget is not None
            )
            if surviving_budget_sum > 0:
                effective_budget = min(intent.total_budget, surviving_budget_sum)
                logger.info(
                    "제외된 슬롯(%s)을 반영하여 기준 총예산을 %s원 -> %s원으로 조정합니다.",
                    excluded_categories,
                    f"{intent.total_budget:,}",
                    f"{effective_budget:,}",
                )

        # [3단계] 조화도 채점 및 Vision Re-ranking
        logger.info("조화도 검수기(Harmonizer) 실행 중... (내부 점수 및 예산 감점 정렬 -> Vision LLM 심사)")
        best_outfits = self.harmonizer.select_best_outfits(
            slot_candidates=slot_candidates,
            tpo_context=intent.tpo_summary,
            top_k=2,
            total_budget=effective_budget,
        )
        logger.info("최종 추천 코디 세트 확정: %d개", len(best_outfits))

        # [4단계] 자연어 응답 생성
        comment = self.responder.generate_coordination_response(user_query, intent.tpo_summary, best_outfits)
        total_prompt_tokens = (
            int(getattr(self.parser, "last_prompt_tokens", 0) or 0)
            + int(getattr(self.harmonizer, "last_prompt_tokens", 0) or 0)
            + int(getattr(self.responder, "last_prompt_tokens", 0) or 0)
        )
        total_completion_tokens = (
            int(getattr(self.parser, "last_completion_tokens", 0) or 0)
            + int(getattr(self.harmonizer, "last_completion_tokens", 0) or 0)
            + int(getattr(self.responder, "last_completion_tokens", 0) or 0)
        )
        return {
            "type": "coordination",
            "query": user_query,
            "tpo": intent.tpo_summary,
            "intent": intent.model_dump() if hasattr(intent, "model_dump") else intent,
            "excluded_categories": excluded_categories,
            "comment": comment,
            "outfits": best_outfits,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "latencies": self._collect_latencies(time.perf_counter() - pipeline_start),
        }
