import logging
from typing import Any
from app.services.query_parser import QueryParser, SlotQuery
from app.services.search_engine import FashionSearchEngine
from app.services.harmonizer import OutfitHarmonizer
from app.services.response_generator import ResponseGenerator
from app.services.size_resolver import SizeProfileResolver

logger = logging.getLogger(__name__)

# 자연어 의도 분석 -> 단품/코디 분기 -> 조화도 검수 -> 응답 생성하는 전체 흐름 총괄

class FashionPipelineCoordinator:
    def __init__(self, cache_service: Any = None):
        logger.info("패션 추천 파이프라인 컴포넌트 초기화 중...")
        self.cache_service = cache_service
        self.parser = QueryParser()
        self.engine = FashionSearchEngine(cache_service=cache_service)
        self.size_resolver = SizeProfileResolver()
        self.harmonizer = OutfitHarmonizer(self.engine)
        self.responder = ResponseGenerator()

        logger.info("전체 파이프라인 준비 완료")


    def _attach_size_info(
            self,
            items: list[dict[str, Any]],
            slot: SlotQuery,
            user_id: str,
    ) -> list[dict[str, Any]]:
        """
        검색된 상품 후보군에 대해 SizeProfileResolver를 통해 최적 사이즈를 산출하고 부착한다.        """
        evaluated_items = []
        for item in items:
            size_result = self.size_resolver.resolve_and_calculate_size(
                user_id=user_id,
                subcategory=slot.subcategory,
                fit_type=slot.fit_type,
                candidate_products=[item],
                category_type=slot.category,
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

    def run(self, user_query: str, user_id: str = "user_001") -> dict[str, Any]:
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
                "intent": intent,
                "excluded_categories": [],
                "comment": "요청에서 검색할 상품을 찾지 못했습니다.",
                "results": [],
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
                "intent": intent,
                "excluded_categories": [] if evaluated_items else [slot.category],
                "comment": comment,
                "results": evaluated_items,
                "prompt_tokens": total_prompt_tokens,
                "completion_tokens": total_completion_tokens,
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
                "intent": intent,
                "excluded_categories": excluded_categories,
                "comment": "요청하신 조건에 맞는 추천 조합을 찾지 못했습니다. 검색 조건을 조금 완화해 다시 시도해주세요.",
                "outfits": [],
                "prompt_tokens": int(getattr(self.parser, "last_prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(self.parser, "last_completion_tokens", 0) or 0),
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
            "intent": intent,
            "excluded_categories": excluded_categories,
            "comment": comment,
            "outfits": best_outfits,
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
        }