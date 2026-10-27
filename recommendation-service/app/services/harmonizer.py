import logging
import os
import time
from itertools import product
from typing import Any, Literal
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

load_dotenv()

# 후보 조합 중 Vision LLM 검수 대상의 최대 개수
MAX_CANDIDATES_TO_REVIEW = 9

# 최종 응답에 포함할 통과 코디의 최대 개수
DEFAULT_TOP_K = 2


SYSTEM_PROMPT = """
당신은 패션 스타일리스트이자 코디 조화도 심사관입니다.

제공된 상품 메타데이터, 상품 이미지, 사용자 요청 상황을 종합해
코디의 시각적 조화와 TPO 적합성을 평가하세요.

[1. 색상 조화]

- 각 상품의 색상 메타데이터(정규화 색상 및 원본 색상)를 기본 색상 판단의 우선 기준으로 사용하세요.
- 정규화 색상(예: gray, ivory)은 검색 분류용 대분류 색상이며, 세부 색감은 함께 제공되는 원본 색상(color_raw, 예: 실버, 차콜, 크림 등)을 참고하세요.
- 이미지의 조명, 그림자, 배경 때문에 색상이 다르게 보이더라도
  메타데이터의 색상을 임의로 변경하지 마세요.
- 이미지에서는 색상 배치, 배색 비율, 패턴, 색상 대비와
  코디 전체의 시각적 조화를 평가하세요.
- 메타데이터(정규화 및 원본 색상)와 이미지가 명백히 불일치하면 그 사실을 피드백에 기록하세요.
  불일치만으로 코디의 색상 조화가 나쁘다고 단정하지 마세요.
- 색상 조합이 실제로 부자연스럽거나 충돌한다고 판단할 근거가 있을 때만
  violated_rules에 "색상 조화"를 포함하세요.
- 특정 색상 조합이라는 이유만으로 무조건 위반 처리하지 마세요.

[2. TPO 적합성]

- 사용자가 요청한 장소, 활동, 격식 수준, 계절 등의 상황에
  착장이 어울리는지 평가하세요.
- 제공된 상품들만을 대상으로 조화와 TPO를 평가하며, 코디에 특정 카테고리(상의, 하의, 신발, 아우터 등)가 빠져 있다는 이유로 위반 처리하거나 감점하지 마세요.
- 명확히 부적합한 아이템이 있을 때만
  violated_rules에 "TPO 부적합"을 포함하세요.
- 무엇이 왜 부적합한지 구체적으로 설명하세요.
- 계절감이 다소 아쉽다는 이유만으로 무조건 탈락시키지 마세요.
  사용자 요청과 명확하게 맞지 않는 경우에만 위반으로 판단하세요.

[3. 계절 정보]

- 상품의 season_candidates 정보가 제공되면 참고 정보로 활용할 수 있습니다.
- 검색 단계에서 계절 선호도를 이미 반영하므로 같은 조건을
  다시 강제 필터링하지 마세요.
- 계절 정보가 없거나 불충분하다면 계절 위반을 임의로 만들지 마세요.

[조화도 점수 기준]

harmony_score는 1부터 100까지의 정수입니다.

- 90~100점: 색상과 배색이 자연스럽고 전체적인 조화가 매우 높음
- 75~89점: 전반적으로 조화롭고 눈에 띄는 문제가 적음
- 60~74점: 무난하지만 색상이나 배색에서 아쉬운 점이 있음
- 40~59점: 조화가 부족하며 눈에 띄는 개선점이 있음
- 1~39점: 색상 충돌이나 배색 문제가 심각함

점수는 전체적인 시각적 조화도를 평가하는 값입니다.
검수 통과 여부를 점수만으로 결정하지 마세요.
높은 점수라도 명확한 TPO 위반이 있으면 탈락할 수 있고,
점수가 상대적으로 낮더라도 명확한 위반이 없으면 통과할 수 있습니다.

[최종 출력 규칙]

- 색상 조화와 TPO 중 하나라도 명확한 위반이 있으면 pass_status는 false입니다.
- 명확한 위반이 없으면(violated_rules가 빈 리스트이면) pass_status는 반드시 true입니다.
- violated_rules에는 실제 위반 항목만 포함하세요.
- 피드백은 한국어 존댓말 2~3문장으로 작성하세요.
- 위반이 있다면 원인과 개선 방향을 구체적으로 설명하세요.
- 위반이 없다면 색상 조화와 상황 적합성의 근거를 설명하세요.
- 이미지나 메타데이터로 확인할 수 없는 사실은 단정하지 마세요.
"""


USER_PROMPT_TEMPLATE = """
[착장 구성 및 상품 메타데이터]
{items_desc}

[사용자 요청 상황(TPO)]
{tpo_context}

[검수 요청]
첨부된 이미지들은 위 상품 목록의 순서와 동일하게 제공됩니다.
상품의 색상 메타데이터를 우선 기준으로 사용하고,
상품 이미지를 참고해 색상 조화와 TPO 적합성을 평가하세요.

상품별 기본 색상, 색상 배치, 배색 비율, 패턴 및 상황 적합성을
고려해 다음 항목을 반환하세요.

- harmony_score: 1~100 정수
- pass_status: 검수 통과 여부
- violated_rules: 실제 위반 기준
- feedback_summary: 한국어 검수 결과 및 근거
"""


class HarmonyGateResult(BaseModel):
    """Vision LLM의 코디 검수 결과."""

    harmony_score: int = Field(
        ge=1,
        le=100,
        description=(
            "코디의 전체적인 시각적 조화도 점수. "
            "1점은 매우 부자연스러움, 100점은 매우 높은 조화도를 의미한다."
        ),
    )
    pass_status: bool = Field(
        description=(
            "색상 조화와 TPO 검수에서 명확한 위반이 없으면 true, "
            "명확한 위반이 있으면 false"
        )
    )
    violated_rules: list[Literal["색상 조화", "TPO 부적합"]] = Field(
        description=(
            "실제로 위반한 기준만 포함한다. "
            "사용 가능한 항목은 '색상 조화', 'TPO 부적합'이다."
        )
    )
    feedback_summary: str = Field(
        description="한국어 존댓말 2~3문장으로 작성한 검수 결과와 근거"
    )


class OutfitHarmonizer:
    SEARCH_SCORE_WEIGHT = 0.5
    VECTOR_HARMONY_WEIGHT = 0.5
    BUDGET_PENALTY_WEIGHT = 0.1

    def __init__(self, search_engine, model_name: str = "gpt-6-astra"):
        self.engine = search_engine
        self.model_name = model_name
        self._client: OpenAI | None = None
        self.last_latency: float = 0.0
        self.last_prompt_tokens: int = 0
        self.last_completion_tokens: int = 0

    def _get_client(self) -> OpenAI:
        if self._client is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY 환경 변수가 설정되지 않았습니다."
                )
            self._client = OpenAI(api_key=api_key)
        return self._client

    def calculate_vector_harmony(
            self,
            items: list[dict[str, Any]],
    ) -> float:
        vectors = []
        for item in items:
            vec = item.get("vector")
            if vec is not None:
                vectors.append(np.asarray(vec, dtype=float))

        if len(vectors) < 2:
            return 80.0

        similarities = []
        for i in range(len(vectors)):
            for j in range(i + 1, len(vectors)):
                v1 = vectors[i]
                v2 = vectors[j]
                norm_product = np.linalg.norm(v1) * np.linalg.norm(v2)
                if norm_product == 0:
                    sim = 0.0
                else:
                    sim = float(np.dot(v1, v2) / norm_product)
                similarities.append(sim)

        if not similarities:
            return 80.0

        avg_sim = float(np.mean(similarities))
        score = float(np.clip((avg_sim - 0.1) / 0.4 * 100, 20, 100))
        return round(score, 2)

    @staticmethod
    def calculate_avg_search_score(
            items: list[dict[str, Any]],
    ) -> float:
        if not items:
            return 0.0

        scores = []
        for item in items:
            raw_score = item.get(
                "composite_score",
                item.get("similarity_score", 0.0),
            )
            scores.append(float(raw_score) * 100.0)

        return round(float(np.mean(scores)), 2)

    @classmethod
    def calculate_budget_penalty(
            cls,
            total_price: int,
            budget_limit: int | None,
    ) -> float:
        if budget_limit is None or budget_limit <= 0:
            return 0.0

        if total_price <= budget_limit:
            return 0.0

        over_ratio = (total_price - budget_limit) / budget_limit
        penalty = over_ratio * (cls.BUDGET_PENALTY_WEIGHT * 100.0)
        return round(penalty, 2)

    def evaluate_final(
            self,
            items: list[dict[str, Any]],
            tpo_context: str,
    ) -> dict[str, Any]:
        items_desc_parts = []
        image_count = 0

        for index, item in enumerate(items, start=1):
            category = item.get("category") or "정보없음"
            subcategory = item.get("subcategory") or "정보없음"
            brand_name = item.get("brand_name") or "브랜드 정보없음"
            product_name = item.get("product_name") or "상품명 없음"

            norm_colors = item.get("color_normalized") or []
            if isinstance(norm_colors, str):
                norm_colors = [norm_colors]

            norm_color_str = ", ".join(str(c) for c in norm_colors if c) or "정보없음"
            raw_color = item.get("color_raw")
            raw_color_str = (
                str(raw_color).strip()
                if raw_color and str(raw_color).strip()
                else "정보없음"
            )

            color_text = (
                f"정규화 색상(color_normalized): {norm_color_str} / "
                f"원본 색상(color_raw): {raw_color_str}"
            )

            seasons = item.get("season_candidates") or []
            if isinstance(seasons, str):
                seasons = [seasons]

            season_text = ", ".join(
                str(season) for season in seasons
            ) or "정보없음"

            items_desc_parts.append(
                f"- 상품 {index}: [{category} - {subcategory}] {brand_name} {product_name}\n"
                f"  색상 메타데이터: {color_text}\n"
                f"  계절 정보: {season_text}"
            )

        items_desc = "\n".join(items_desc_parts)

        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": USER_PROMPT_TEMPLATE.format(
                    items_desc=items_desc,
                    tpo_context=tpo_context or "별도 상황 지정 없음",
                ),
            }
        ]

        for item in items:
            image_url = item.get("image_url")
            if not image_url:
                continue

            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image_url,
                        "detail": "high",
                    },
                }
            )
            image_count += 1

        if image_count == 0:
            raise ValueError(
                "코디 검수에 사용할 상품 이미지 URL이 없습니다."
            )

        client = self._get_client()

        start_time = time.perf_counter()

        completion = client.beta.chat.completions.parse(
            model=self.model_name,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": content,
                },
            ],
            response_format=HarmonyGateResult
        )

        end_time = time.perf_counter()

        self.last_latency = end_time - start_time
        usage = getattr(completion, "usage", None)
        p_tok = int(getattr(usage, "prompt_tokens", 0) or 0)
        c_tok = int(getattr(usage, "completion_tokens", 0) or 0)
        logger.debug("Harmonizer 단일 (%s) 응답 시간: %.4f초, tokens=(prompt=%d, completion=%d)", self.model_name, self.last_latency, p_tok, c_tok)

        message = completion.choices[0].message

        if message.refusal:
            raise RuntimeError(
                f"Vision LLM이 검수 요청을 거부했습니다: {message.refusal}"
            )

        result = message.parsed

        if result is None:
            raise RuntimeError(
                "Vision LLM 응답을 HarmonyGateResult로 파싱하지 못했습니다."
            )

        deduped_rules = list(dict.fromkeys(result.violated_rules))
        consistent_pass_status = len(deduped_rules) == 0

        return {
            "harmony_score": result.harmony_score,
            "pass_status": consistent_pass_status,
            "violated_rules": deduped_rules,
            "feedback_summary": result.feedback_summary,
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
        }

    def select_best_outfits(
            self,
            slot_candidates: dict[str, list[dict[str, Any]]],
            tpo_context: str,
            top_k: int = DEFAULT_TOP_K,
            total_budget: int | None = None,
            pre_filtered_combos: list[tuple] | None = None,
    ) -> list[dict[str, Any]]:
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0

        if top_k < 1:
            raise ValueError("top_k는 1 이상이어야 합니다.")

        if pre_filtered_combos is not None:
            all_combos = pre_filtered_combos
        else:
            if not slot_candidates:
                return []

            slots = [
                slot for slot, items in slot_candidates.items() if items
            ]

            if not slots:
                return []

            all_combos = list(
                product(*(slot_candidates[slot] for slot in slots))
            )

        if not all_combos:
            return []

        ranked: list[dict[str, Any]] = []

        for combo in all_combos:
            items = list(combo)

            total_price = sum(
                int(item.get("price") or 0)
                for item in items
            )

            avg_search_score = self.calculate_avg_search_score(items)
            vector_score = self.calculate_vector_harmony(items)

            fit_scores = []
            has_outlier_size = False

            for item in items:
                recommendation = item.get("size_recommendation")
                if (
                        recommendation
                        and recommendation.get("predicted_fit_score") is not None
                ):
                    fit_score = float(recommendation["predicted_fit_score"])
                    if fit_score == 0.0:
                        has_outlier_size = True
                    fit_scores.append(fit_score * 100.0)

            if fit_scores:
                avg_fit_score = round(sum(fit_scores) / len(fit_scores), 2)
                base_score = (
                        (avg_search_score * 0.4)
                        + (vector_score * 0.4)
                        + (avg_fit_score * 0.2)
                )
            else:
                avg_fit_score = None
                if len(items) == 1:
                    base_score = avg_search_score
                else:
                    base_score = (
                            (avg_search_score * self.SEARCH_SCORE_WEIGHT)
                            + (vector_score * self.VECTOR_HARMONY_WEIGHT)
                    )

            budget_penalty = self.calculate_budget_penalty(
                total_price=total_price,
                budget_limit=total_budget,
            )

            composite_score = base_score - budget_penalty

            if has_outlier_size:
                composite_score -= 50.0

            ranked.append(
                {
                    "items": items,
                    "total_price": total_price,
                    "avg_search_score": avg_search_score,
                    "vector_score": vector_score,
                    "avg_fit_score": avg_fit_score,
                    "budget_penalty": budget_penalty,
                    "composite_score": round(composite_score, 2),
                }
            )

        ranked.sort(
            key=lambda candidate: candidate["composite_score"],
            reverse=True,
        )

        candidates_to_review = ranked[:MAX_CANDIDATES_TO_REVIEW]

        passed_outfits: list[dict[str, Any]] = []
        rejected_outfits: list[dict[str, Any]] = []

        for candidate in candidates_to_review:
            try:
                gate_result = self.evaluate_final(
                    candidate["items"],
                    tpo_context,
                )
            except Exception as error:
                logger.warning(
                    "후보 코디 Vision 검수 실패로 해당 후보를 건너뜁니다: %s: %s",
                    type(error).__name__,
                    error,
                )
                continue

            self.last_prompt_tokens += int(gate_result.get("prompt_tokens", 0) or 0)
            self.last_completion_tokens += int(gate_result.get("completion_tokens", 0) or 0)

            final_score = round(
                gate_result["harmony_score"] - candidate["budget_penalty"],
                2,
                )

            outfit_data = {
                "harmony_score": gate_result["harmony_score"],
                "final_score": final_score,
                "budget_penalty": candidate["budget_penalty"],
                "pass_status": gate_result["pass_status"],
                "violated_rules": gate_result["violated_rules"],
                "verdict": gate_result["feedback_summary"],
                "styling_tip": gate_result["feedback_summary"],
                "total_price": candidate["total_price"],
                "avg_search_score": candidate["avg_search_score"],
                "vector_score": candidate["vector_score"],
                "items": candidate["items"],
            }

            if gate_result["pass_status"]:
                passed_outfits.append(outfit_data)
            else:
                rejected_outfits.append(outfit_data)

        passed_outfits.sort(
            key=lambda outfit: outfit["final_score"],
            reverse=True,
        )

        if not passed_outfits and rejected_outfits:
            logger.info("모든 후보가 Vision Gate 기준을 통과하지 못해 차선책 후보를 반환합니다.")
            rejected_outfits.sort(
                key=lambda outfit: outfit["final_score"],
                reverse=True,
            )
            return rejected_outfits[:top_k]

        return passed_outfits[:top_k]