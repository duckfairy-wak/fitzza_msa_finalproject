import logging
import os
import time
from contextvars import ContextVar
from openai import OpenAI
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

_responder_prompt_tokens_ctx: ContextVar[int] = ContextVar("responder_prompt_tokens_ctx", default=0)
_responder_completion_tokens_ctx: ContextVar[int] = ContextVar("responder_completion_tokens_ctx", default=0)

class ResponseGenerator:
    def __init__(self, model_name: str = "gpt-6-luna"):
        self.model_name = model_name
        self._client: OpenAI | None = None
        self.last_latency: float = 0.0

    @property
    def last_prompt_tokens(self) -> int:
        return _responder_prompt_tokens_ctx.get()

    @last_prompt_tokens.setter
    def last_prompt_tokens(self, val: int) -> None:
        _responder_prompt_tokens_ctx.set(int(val or 0))

    @property
    def last_completion_tokens(self) -> int:
        return _responder_completion_tokens_ctx.get()

    @last_completion_tokens.setter
    def last_completion_tokens(self, val: int) -> None:
        _responder_completion_tokens_ctx.set(int(val or 0))

    def _get_client(self) -> OpenAI:
        """실제 API 호출이 필요할 때 OpenAI 클라이언트를 준비한다."""
        if self._client is not None:
            return self._client

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY 환경변수가 설정되지 않았습니다."
            )

        self._client = OpenAI(api_key=api_key)
        return self._client

    @staticmethod
    def _translate_category(category: str) -> str:
        """영문 대분류 카테고리를 직관적인 한글 명칭으로 변환한다."""
        mapping = {
            "outer": "아우터",
            "top": "상의",
            "bottom": "하의",
            "shoes": "신발",
            "hat": "모자",
        }
        return mapping.get(category.lower(), category)

    def generate_single_response(self, query: str, tpo: str, items: list) -> str:
        """단일 상품 추천 결과에 대한 매니저 코멘트 생성"""
        item_summaries = []
        for item in items:
            brand = item.get("brand_name", "브랜드")
            name = item.get("product_name", "상품명")
            subcat = item.get("subcategory")
            subcat_str = f" ({subcat})" if subcat and subcat != "정보없음" else ""
            price = item.get("price")
            price_str = f"{price:,}원" if price is not None else "가격미상"
            item_summaries.append(f"- {brand} {name}{subcat_str} - {price_str}")

        summary_text = "\n".join(item_summaries) if item_summaries else "추천 상품 없음"

        prompt = f"""
        사용자 질의: "{query}"
        상황(TPO): {tpo}
        추천된 단품 목록:
        {summary_text}

        [엄격한 제약 사항]:
        1. 반드시 위 '추천된 단품 목록'에 실제로 포함된 상품명과 브랜드만 언급하세요. 목록에 없는 상품을 임의로 지어내거나 추천하지 마세요.
        2. 위 상품들을 바탕으로 사용자의 요청에 딱 맞춘 추천 코멘트를 정중하고 센스 있는 패션 매니저 말투(한국어)로 2~3문장 작성하세요.
        """

        client = self._get_client()

        start_time = time.perf_counter()

        res = client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}]
        )

        end_time = time.perf_counter()

        self.last_latency = end_time - start_time
        usage = getattr(res, "usage", None)
        self.last_prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        self.last_completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        logger.debug("ResponseGenerator 단일 (%s) 응답 시간: %.4f초, tokens=(prompt=%d, completion=%d)", self.model_name, self.last_latency, self.last_prompt_tokens, self.last_completion_tokens)
        return res.choices[0].message.content

    def generate_coordination_response(self, query: str, tpo: str, outfits: list) -> str:
        """코디 세트 추천 결과에 대한 패션 에디터 코멘트 생성"""
        outfit_summaries = []
        for idx, outfit in enumerate(outfits, 1):
            total_price = outfit.get("total_price")
            price_str = f"{total_price:,}원" if total_price is not None else "가격미상"

            outfit_text = f"[[ 코디 세트 {idx} (총 예상 가격: {price_str}) ]]\n"

            for item in outfit.get("items", []):
                brand = item.get("brand_name", "브랜드")
                name = item.get("product_name", "상품명")
                raw_cat = item.get("category", "의류")
                category = self._translate_category(raw_cat)
                subcat = item.get("subcategory")
                display_cat = subcat if subcat and subcat != "정보없음" else category
                price = item.get("price")
                item_price_str = f", {price:,}원" if price is not None else ""

                outfit_text += f"- [{display_cat}] {brand} {name} ({item_price_str.lstrip(', ')})\n"

            verdict = outfit.get("verdict", "톤과 실루엣이 자연스럽게 어우러지는 조합입니다.")
            outfit_text += f"* AI 에디터 평가 및 스타일링 팁: {verdict}\n"

            outfit_summaries.append(outfit_text)

        summary_text = "\n\n".join(outfit_summaries) if outfit_summaries else "추천 코디 없음"

        prompt = f"""
        사용자 질의: "{query}"
        상황(TPO): {tpo}
        추천 코디 세트 정보:
        {summary_text}

        [엄격한 제약 사항]:
        1. 반드시 위 '추천 코디 세트 정보'에 명시된 실제 상품들(브랜드명, 상품명, 카테고리, 가격)만 정확히 인용하세요. 목록에 없는 아이템을 임의로 지어내어 추천하지 마세요.
        2. AI 에디터 평가 포인트에 기반하여 각 코디 세트의 매력을 설명하되, 존재하지 않는 스펙이나 가격을 만들어내지 마세요.

        당신은 최고의 패션 매거진 에디터입니다. 위 제약 사항을 준수하며 각 코디 세트의 매력과 TPO 적합성을 설명하는 추천 코멘트를 매끄럽고 세련되게 작성하세요.
        """

        client = self._get_client()

        start_time = time.perf_counter()

        res = client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}]
        )

        end_time = time.perf_counter()

        self.last_latency = end_time - start_time
        usage = getattr(res, "usage", None)
        self.last_prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        self.last_completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        logger.debug("ResponseGenerator 코디 (%s) 응답 시간: %.4f초, tokens=(prompt=%d, completion=%d)", self.model_name, self.last_latency, self.last_prompt_tokens, self.last_completion_tokens)
        return res.choices[0].message.content
