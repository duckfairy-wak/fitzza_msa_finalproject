import logging
import os
import json
import datetime
import time
from zoneinfo import ZoneInfo
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import Literal
from dotenv import load_dotenv
from contextvars import ContextVar
from app.services.color_palette import FILTERABLE_COLORS

logger = logging.getLogger(__name__)

# OpenAI를 활용해 사용자의 한국어 질의를 파싱
load_dotenv()

_parser_prompt_tokens_ctx: ContextVar[int] = ContextVar("parser_prompt_tokens_ctx", default=0)
_parser_completion_tokens_ctx: ContextVar[int] = ContextVar("parser_completion_tokens_ctx", default=0)

ColorLiteral = Literal.__getitem__(tuple(FILTERABLE_COLORS))

SubcategoryLiteral = Literal[
    # 아우터
    "후드 집업", "블루종/MA-1", "레더/라이더스 재킷", "슈트/블레이저 재킷", "카디건",
    "경량 패딩/패딩 베스트", "사파리/헌팅 재킷", "트러커 재킷", "스타디움 재킷",
    "나일론/코치 재킷", "트레이닝 재킷", "아노락 재킷", "플리스/뽀글이", "환절기 코트",
    "베스트", "무스탕/퍼", "겨울 싱글 코트", "겨울 더블 코트", "겨울 기타 코트",
    "숏패딩/헤비 아우터", "롱패딩/헤비 아우터", "기타 아우터",
    # 상의
    "긴소매 티셔츠", "맨투맨/스웨트", "셔츠/블라우스", "후드 티셔츠", "반소매 티셔츠",
    "피케/카라 티셔츠", "니트/스웨터", "민소매 티셔츠", "기타 상의",
    # 바지
    "데님 팬츠", "트레이닝/조거 팬츠", "코튼 팬츠", "슈트 팬츠/슬랙스", "숏 팬츠",
    "레깅스", "점프 슈트/오버올", "기타 하의",
    # 모자
    "캡/야구모자", "헌팅캡/베레모", "페도라", "버킷/사파리햇", "비니", "트루퍼",
    "바라클라바", "기타 모자",
    # 신발
    "스니커즈", "스포츠화", "구두", "부츠/워커", "샌들/슬리퍼", "패딩/퍼 신발", "신발용품"
]

# 코디 추천 시 개별 아이템(슬롯)의 검색 조건
class SlotQuery(BaseModel):
    category: Literal["outer", "top", "bottom", "shoes", "hat"] = Field(
        description="무신사 5대 대분류 카테고리"
    )
    subcategory: SubcategoryLiteral | None = Field(
        default=None,
        description="질의에서 서브카테고리가 명확히 드러날 경우 아래 목록 중 선택. 모호하면 null"
    )
    clip_query_en: str = Field(
        description="Fashion-CLIP 검색용 패션 영문 시각 묘사"
    )
    slot_budget: int | None = Field(
        default=None,
        ge=1,
        description="LLM이 배분한 슬롯별 예산(원). 총예산이 없으면 null"
    )
    max_price: int | None = Field(
        default=None,
        ge=1,
        description="LLM이 결정한 검색용 슬롯별 최대 가격. 총예산이 없으면 null"
    )
    color: ColorLiteral | None = Field(
        default=None,
        description="질의에서 명시된 색상(영문 소문자). 없으면 null"
    )
    fit_type: Literal[
                  "스키니", "슬림", "레귤러", "루즈", "오버 사이즈"
              ] | None = Field(
        default=None,
        description="질의에서 명시된 핏. 없으면 null"
    )
    touch_type: Literal[
                    "부드러움", "약간 부드러움", "보통", "약간 뻣뻣함", "뻣뻣함"
                ] | None = Field(
        default=None,
        description="질의에서 명시된 촉감. 없으면 null"
    )
    stretch_type: Literal[
                      "없음", "거의 없음", "보통", "약간 있음", "있음"
                  ] | None = Field(
        default=None,
        description="질의에서 명시된 신축성. 없으면 null"
    )
    transparency_type: Literal[
                           "있음", "약간 있음", "보통", "거의 없음", "없음"
                       ] | None = Field(
        default=None,
        description="질의에서 명시된 비침 정도. 없으면 null"
    )
    thickness_type: Literal[
                        "얇음", "약간 얇음", "보통", "약간 두꺼움", "두꺼움"
                    ] | None = Field(
        default=None,
        description="질의에서 명시된 두께. 없으면 null"
    )


# 전체 질의의 맥락과 공통 조건
class ParsedIntent(BaseModel):
    search_type: Literal["single", "coordination"] = Field(
        description="단품 검색 vs 코디 세트 추천"
    )
    total_budget: int | None = Field(
        default=None,
        ge=0,
        description="사용자가 언급한 총예산(원 단위 정수). 없으면 null"
    )
    season_preferences: list[
        Literal["봄", "여름", "가을", "겨울"]
    ] = Field(
        min_length=1,
        description="계절 우선순위 배열. 최소 한 계절"
    )
    tpo_summary: str = Field(
        description="TPO 및 스타일 무드 요약"
    )
    slots: list[SlotQuery] = Field(
        description="LLM이 선택한 검색 대상 아이템 목록"
    )


class QueryParser:
    def __init__(self, model_name: str = "gpt-6.1-sol"):
        self.model_name = model_name
        self._client: OpenAI | None = None
        self.last_latency: float = 0.0

    @property
    def last_prompt_tokens(self) -> int:
        return _parser_prompt_tokens_ctx.get()

    @last_prompt_tokens.setter
    def last_prompt_tokens(self, val: int) -> None:
        _parser_prompt_tokens_ctx.set(int(val or 0))

    @property
    def last_completion_tokens(self) -> int:
        return _parser_completion_tokens_ctx.get()

    @last_completion_tokens.setter
    def last_completion_tokens(self, val: int) -> None:
        _parser_completion_tokens_ctx.set(int(val or 0))

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
    def _get_current_season(month: int) -> str:
        if month in (3, 4, 5):
            return "봄"
        if month in (6, 7, 8):
            return "여름"
        if month in (9, 10, 11):
            return "가을"
        return "겨울"

    @staticmethod
    def _example_json(data: dict) -> str:
        return json.dumps(data, ensure_ascii=False)

    def parse(self, user_query: str) -> ParsedIntent:
        if not user_query or not user_query.strip():
            raise ValueError("사용자 질의는 비어 있을 수 없습니다.")

        client = self._get_client()

        current_month = datetime.datetime.now(
            ZoneInfo("Asia/Seoul")
        ).month
        current_season = self._get_current_season(current_month)

        # 현재 계절을 활용하는 Few-shot 예시용 값
        generic_season = [current_season]

        system_prompt = f"""
            당신은 패션 커머스 플랫폼의 AI 스타일리스트이자 데이터 파서입니다.

            사용자의 한국어 질의를 분석해 ParsedIntent 스키마에 맞는
            구조화된 결과를 반환하세요.

            카테고리 선택, 서브카테고리 매핑, 검색 조건 생성, 예산 배분은 모두 LLM이 결정합니다.
            Python에서 결과를 보정하지 않습니다.

            ============================================================
            1. search_type 및 검색 대상
            ============================================================

            search_type은 다음 두 가지 중 하나입니다.

            - single: 특정 상품 하나를 추천하는 요청
            - coordination: 여러 상품을 조합해 코디를 추천하는 요청

            [단일 상품 추천]

            "A에 어울리는 B", "A에 신을 B 추천해줘"처럼
            기준 아이템 A와 조합할 타겟 상품 B 하나를 요청하면
            single로 분류하고, 구매 대상인 B만 슬롯으로 추출하세요.

            A는 코디 참고 대상이므로 검색 슬롯에 포함하지 않습니다.

            예시:
            - "청바지에 어울리는 신발 추천해줘"
              -> single, shoes만 검색
            - "흰 셔츠에 어울리는 바지 추천해줘"
              -> single, bottom만 검색
            - "검은색 패딩 추천해줘"
              -> single, outer만 검색

            [여러 상품 코디 추천]

            사용자가 여러 상품을 함께 추천해 달라고 요청한 경우
            coordination으로 분류하세요.

            ============================================================
            2. category 및 subcategory (서브카테고리) 선택 정책
            ============================================================

            무신사 5대 대분류와 각 허용된 서브카테고리 목록은 다음과 같습니다.

            - outer (아우터):
              후드 집업, 블루종/MA-1, 레더/라이더스 재킷, 슈트/블레이저 재킷, 카디건, 경량 패딩/패딩 베스트, 사파리/헌팅 재킷, 트러커 재킷, 스타디움 재킷, 나일론/코치 재킷, 트레이닝 재킷, 아노락 재킷, 플리스/뽀글이, 환절기 코트, 베스트, 무스탕/퍼, 겨울 싱글 코트, 겨울 더블 코트, 겨울 기타 코트, 숏패딩/헤비 아우터, 롱패딩/헤비 아우터, 기타 아우터
            - top (상의):
              긴소매 티셔츠, 맨투맨/스웨트, 셔츠/블라우스, 후드 티셔츠, 반소매 티셔츠, 피케/카라 티셔츠, 니트/스웨터, 민소매 티셔츠, 기타 상의
            - bottom (바지):
              데님 팬츠, 트레이닝/조거 팬츠, 코튼 팬츠, 슈트 팬츠/슬랙스, 숏 팬츠, 레깅스, 점프 슈트/오버올, 기타 하의
            - shoes (신발):
              스니커즈, 스포츠화, 구두, 부츠/워커, 샌들/슬리퍼, 패딩/퍼 신발, 신발용품
            - hat (모자):
              캡/야구모자, 헌팅캡/베레모, 페도라, 버킷/사파리햇, 비니, 트루퍼, 바라클라바, 기타 모자

            [정책 A: 단일 상품]
            - 사용자가 추천받으려는 상품의 카테고리 하나만 선택하세요.
            - 사용자의 질의에 특정 품목(예: "후드티", "슬랙스", "라이더스 자켓", "스니커즈" 등)이 명시되어 있다면, 해당 대분류에 속하는 위 허용 목록 중 가장 정확한 항목을 `subcategory`에 지정하세요.
            - 특정 품목 언급 없이 포괄적인 단품을 요청했다면 `subcategory`는 `null`로 설정하세요.
            - 기준 아이템이나 코디 참고용 상품은 검색 슬롯에 포함하지 않습니다.

            [정책 B: 카테고리를 명시한 코디]
            - 사용자가 코디에 포함할 카테고리나 품목을 명시했다면(예: "블레이저와 슬랙스 코디"), 명시된 카테고리만 선택하세요.
            - 각 슬롯별로 언급된 품목에 부합하는 `subcategory`를 정확히 매핑하세요. (예: 블레이저 -> `슈트/블레이저 재킷`, 슬랙스 -> `슈트 팬츠/슬랙스`)
            - 명시하지 않은 카테고리를 임의로 추가하지 마세요.

            [정책 C: 일반적인 코디]
            - "데이트룩 코디", "출근룩 추천", "여행 코디"처럼 구체적인 품목이나 카테고리를 지정하지 않은 일반적인 코디 요청은 기본적으로 다음 세 가지를 선택하세요: `top`, `bottom`, `shoes`.
            - 일반적인 코디 요청의 경우, 각 슬롯의 `subcategory`는 **반드시 `null`**로 비워두세요. (임의로 특정 바지나 상의 종류를 서브카테고리로 고정하지 마세요.)
            - 요청한 TPO와 계절을 고려해 필요하다면 `outer` 또는 `hat`을 추가할 수 있으며, 이 경우에도 특정 품목 지정이 없다면 `subcategory`는 `null`입니다.

            [정책 D: 검색 조건 생성]
            - 선택한 모든 슬롯에 대해 실제 검색에 사용할 수 있는 구체적인 `clip_query_en`을 작성하세요.

            ============================================================
            3. total_budget, slot_budget 및 max_price
            ============================================================

            total_budget은 사용자가 언급한 전체 예산을 원 단위 정수로 추출하세요.

            예시:
            - "15만원 이하" -> 150000
            - "총 20만원 정도" -> 200000
            - "20만원대" -> 200000
            - 예산 언급 없음 -> null

            개별 상품 예산과 전체 코디 예산을 구분하세요.
            개별 상품의 가격 상한을 전체 코디 예산으로 잘못 해석하지 마세요.

            [slot_budget]

            총예산이 있다면 선택한 모든 슬롯에 예산을 직접 배분하세요.

            - 단일 상품은 해당 상품에 전체 예산을 배정할 수 있습니다.
            - 코디는 상품 종류, 가격대, 중요도를 고려해 차등 배분하세요.
            - 모든 카테고리에 동일한 예산을 배분할 필요는 없습니다.
            - 신발이나 아우터처럼 상대적으로 가격대가 높을 수 있는 상품은
              더 많은 예산을 배정할 수 있습니다.
            - 사용자가 특정 카테고리에 별도 예산을 지정했다면 이를 우선하세요.
            - 슬롯별 slot_budget 합계는 total_budget을 초과하지 않아야 합니다.
            - 가능한 경우 슬롯별 예산 합계가 total_budget과 일치하도록 하세요.

            총예산이 없다면 모든 슬롯의 slot_budget은 null입니다.

            [max_price]

            max_price는 해당 카테고리에서 검색할 상품의 최대 가격입니다.

            검색 후보를 확보할 수 있도록 slot_budget을 기준으로 결정하세요.
            기본적으로 slot_budget의 약 1.3배를 참고할 수 있습니다.

            예시:
            - slot_budget: 40000
            - max_price: 52000

            max_price는 검색 후보를 확보하기 위한 가격 상한입니다.
            최종 추천 상품의 총가격이 total_budget을 초과해도 된다는 뜻은 아닙니다.

            총예산이 없다면 max_price도 null입니다.

            slot_budget과 max_price를 모두 직접 결정하세요.
            Python에서 예산을 재배분하거나 max_price를 계산하지 않습니다.

            ============================================================
            4. season_preferences
            ============================================================

            상품 자체에 적합한 계절을 판단하세요.

            계절 판단 우선순위:
            1. 상품 자체의 일반적인 계절 적합성
            2. 사용자가 명시한 계절
            3. 현재 월의 계절

            예시:
            - 반팔 티셔츠는 12월에 입더라도 상품 계절은 ["여름"]
            - 패딩은 ["겨울"]
            - 트렌치코트는 ["봄", "가을"]로 판단할 수 있음

            단, 사용자가 "가을에 입을 니트"처럼 특정 계절을 명시했다면
            그 요청을 우선해 ["가을"]로 반환하세요.

            - "사계절용"처럼 사계절 착용을 명시한 경우에만
              ["봄", "여름", "가을", "겨울"]을 반환하세요.
            - "봄가을용"처럼 복수 계절을 명시했다면
              ["봄", "가을"]처럼 해당 계절만 반환하세요.
            - 계절감이 뚜렷하지 않은 범용 상품은 현재 월의 계절을 사용하세요.
            - 빈 배열이나 null을 반환하지 말고 유효한 계절을 하나 이상 반환하세요.

            현재 한국 시간 기준 계절은 {current_season}입니다.
            현재 계절은 참고 정보이며, 명시적인 사용자 요청을 무시하는
            근거로 사용하지 마세요.

            ============================================================
            5. clip_query_en
            ============================================================

            Fashion-CLIP이 이해하기 좋은 구체적인 영문 시각 묘사를 작성하세요.

            상품 종류, 색상, 핏, 실루엣, 길이, 패턴, 소재의 시각적 특징을
            사용자 요청과 코디 맥락에 맞게 반영하세요.

            예시:
            - "검은색 패딩" -> "black puffer jacket"
            - "흰색 오버핏 셔츠" -> "oversized white button-up shirt"
            - "실버 스니커즈" -> "silver metallic sneakers"

            사용자가 명시한 카테고리, 색상, 핏, 스타일을 반영하세요.
            검색 대상과 관련 없는 특징을 임의로 추가하지 마세요.

            계절이나 두께가 명시되지 않았다면 상품 종류만으로
            두께나 소재를 추측해 추가하지 마세요.

            사용자가 말하지 않은 색상, 핏, 소재를 확정된 조건처럼
            추가하지 않습니다.

            영어로 작성하고 실제 상품 검색에 사용할 수 있을 만큼 구체적으로
            표현하세요.

            ============================================================
            6. color
            ============================================================

            사용자가 명시한 색상만 추출하고, 반드시 아래 허용 목록 중 하나로 정규화하세요.

            허용된 표준 색상:
            {", ".join(FILTERABLE_COLORS)}

            색상 정규화 예시:
            - 검은색 -> black
            - 파란색 -> blue
            - 네이비 -> navy
            - 흰색 -> white
            - 회색 -> gray
            - 은색 -> gray
            - 아이보리 -> ivory
            - 크림색 -> ivory
            - 베이지 -> beige
            - 갈색 -> brown

            색상을 언급하지 않았다면 null입니다.

            위 예시는 허용 목록에 해당 색상이 존재하는 경우에만 적용하세요.
            허용 목록에 없는 색상은 임의의 값으로 반환하지 마세요.

            코디에 어울리는 색상이라는 이유만으로 사용자가 명시하지 않은
            색상을 color 필터에 넣지 마세요.

            ============================================================
            7. fit_type
            ============================================================

            반드시 다음 값 중 하나를 사용하세요.

            - 스키니
            - 슬림
            - 레귤러
            - 루즈
            - 오버 사이즈

            정규화 규칙:
            - 스키니핏 -> 스키니
            - 슬림핏 -> 슬림
            - 정핏, 기본 핏 -> 의미가 명확할 때만 레귤러
            - 루즈핏 -> 루즈
            - 오버핏, 오버사이즈핏 -> 오버 사이즈

            핏을 명시하지 않았다면 null입니다.

            "편안한", "스트릿한", "캐주얼한" 등의 표현만으로
            핏을 추측하지 마세요.

            ============================================================
            8. touch_type
            ============================================================

            허용값:
            - 부드러움
            - 약간 부드러움
            - 보통
            - 약간 뻣뻣함
            - 뻣뻣함

            촉감을 명시하지 않았다면 null입니다.

            ============================================================
            9. stretch_type
            ============================================================

            허용값:
            - 없음
            - 거의 없음
            - 보통
            - 약간 있음
            - 있음

            신축성을 명시하지 않았다면 null입니다.

            ============================================================
            10. transparency_type
            ============================================================

            허용값:
            - 있음
            - 약간 있음
            - 보통
            - 거의 없음
            - 없음

            비침 정도를 명시하지 않았다면 null입니다.

            ============================================================
            11. thickness_type
            ============================================================

            허용값:
            - 얇음
            - 약간 얇음
            - 보통
            - 약간 두꺼움
            - 두꺼움

            두께를 명시하지 않았다면 null입니다.

            계절이나 TPO만을 근거로 사용자가 요청하지 않은
            두께 필터를 설정하지 마세요.

            ============================================================
            12. tpo_summary
            ============================================================

            사용자가 언급한 착용 상황과 스타일 무드를
            한국어 한 문장으로 요약하세요.

            TPO 예시:
            - 하객룩
            - 출근룩
            - 데이트룩
            - 여행룩
            - 일상복

            스타일 무드 예시:
            - 미니멀
            - 캐주얼
            - 스트릿
            - 포멀

            착용 상황이나 스타일 무드가 없다면 상품 종류와
            명시된 조건을 요약하세요.

            착용 시기가 명시되어 있다면 상품의 계절 적합성과 별개로
            요약에 보존할 수 있습니다.

            새로운 장소, 상황, 무드를 임의로 만들지 마세요.
            tpo_summary는 한국어 요약이며 clip_query_en과 구분하세요.

            ============================================================
            13. 최종 출력 규칙
            ============================================================

            - ParsedIntent 스키마에 맞는 구조화된 결과를 반환하세요.
            - 각 슬롯은 SlotQuery 스키마에 맞춰 작성하세요.
            - 단일 상품 추천은 구매 대상 상품 하나만 포함하세요.
            - 카테고리를 명시한 코디는 명시된 카테고리만 포함하세요.
            - 일반 코디는 top, bottom, shoes를 기본으로 선택하세요.
            - outer와 hat은 필요할 때만 추가하세요.
            - 검색 필터는 사용자가 명시한 경우에만 설정하세요.
            - 예산과 가격 상한을 직접 결정하세요.
            - Python에서 카테고리나 예산을 보정하지 않는다는 점을 고려해
              처음부터 요청에 맞는 결과를 생성하세요.
            """

        # Few-shot 예시
        examples = [
            (
                "연청색 바지에 신을 실버 스니커즈 추천해줘",
                {
                    "search_type": "single",
                    "total_budget": None,
                    "season_preferences": generic_season,
                    "tpo_summary": "연청색 바지에 어울리는 실버 스니커즈 추천",
                    "slots": [{
                        "category": "shoes",
                        "subcategory": "스니커즈",
                        "clip_query_en": "silver metallic sneakers",
                        "slot_budget": None,
                        "max_price": None,
                        "color": "gray",
                        "fit_type": None,
                        "touch_type": None,
                        "stretch_type": None,
                        "transparency_type": None,
                        "thickness_type": None,
                    }],
                },
            ),
            (
                "하객룩으로 입을 깔끔한 블레이저랑 슬랙스 세트 찾아줘",
                {
                    "search_type": "coordination",
                    "total_budget": None,
                    "season_preferences": ["봄", "가을"],
                    "tpo_summary": "결혼식 하객룩에 어울리는 단정하고 깔끔한 포멀 스타일",
                    "slots": [
                        {
                            "category": "outer",
                            "subcategory": "슈트/블레이저 재킷",
                            "clip_query_en": "clean formal blazer jacket",
                            "slot_budget": None,
                            "max_price": None,
                            "color": None,
                            "fit_type": None,
                            "touch_type": None,
                            "stretch_type": None,
                            "transparency_type": None,
                            "thickness_type": None,
                        },
                        {
                            "category": "bottom",
                            "subcategory": "슈트 팬츠/슬랙스",
                            "clip_query_en": "formal dress pants slacks",
                            "slot_budget": None,
                            "max_price": None,
                            "color": None,
                            "fit_type": None,
                            "touch_type": None,
                            "stretch_type": None,
                            "transparency_type": None,
                            "thickness_type": None,
                        },
                    ],
                },
            ),
            (
                "스트릿하게 입기 좋은 오버사이즈 후드티 찾아줘",
                {
                    "search_type": "single",
                    "total_budget": None,
                    "season_preferences": generic_season,
                    "tpo_summary": "스트릿한 무드의 오버사이즈 후드티 추천",
                    "slots": [{
                        "category": "top",
                        "subcategory": "후드 티셔츠",
                        "clip_query_en": "street style oversized hoodie",
                        "slot_budget": None,
                        "max_price": None,
                        "color": None,
                        "fit_type": "오버 사이즈",
                        "touch_type": None,
                        "stretch_type": None,
                        "transparency_type": None,
                        "thickness_type": None,
                    }],
                },
            ),
            (
                "15만원 이하로 가을에 입기 좋은 니트랑 데님 팬츠 코디 추천해줘",
                {
                    "search_type": "coordination",
                    "total_budget": 150000,
                    "season_preferences": ["가을"],
                    "tpo_summary": "가을철 캐주얼한 니트와 데님 팬츠 코디",
                    "slots": [
                        {
                            "category": "top",
                            "subcategory": "니트/스웨터",
                            "clip_query_en": "casual knit sweater",
                            "slot_budget": 80000,
                            "max_price": 104000,
                            "color": None,
                            "fit_type": None,
                            "touch_type": None,
                            "stretch_type": None,
                            "transparency_type": None,
                            "thickness_type": None,
                        },
                        {
                            "category": "bottom",
                            "subcategory": "데님 팬츠",
                            "clip_query_en": "casual denim jeans",
                            "slot_budget": 70000,
                            "max_price": 91000,
                            "color": None,
                            "fit_type": None,
                            "touch_type": None,
                            "stretch_type": None,
                            "transparency_type": None,
                            "thickness_type": None,
                        },
                    ],
                },
            ),
            (
                "봄가을용으로 입기 좋은 트렌치코트 찾아줘",
                {
                    "search_type": "single",
                    "total_budget": None,
                    "season_preferences": ["봄", "가을"],
                    "tpo_summary": "봄과 가을에 활용하기 좋은 클래식 트렌치코트",
                    "slots": [{
                        "category": "outer",
                        "subcategory": "환절기 코트",
                        "clip_query_en": "classic trench coat",
                        "slot_budget": None,
                        "max_price": None,
                        "color": None,
                        "fit_type": None,
                        "touch_type": None,
                        "stretch_type": None,
                        "transparency_type": None,
                        "thickness_type": None,
                    }],
                },
            ),
            (
                "12월에 입을 반팔 티셔츠 추천해줘",
                {
                    "search_type": "single",
                    "total_budget": None,
                    "season_preferences": ["여름"],
                    "tpo_summary": "12월에 착용할 반팔 티셔츠 추천",
                    "slots": [{
                        "category": "top",
                        "subcategory": "반소매 티셔츠",
                        "clip_query_en": "short sleeve t-shirt",
                        "slot_budget": None,
                        "max_price": None,
                        "color": None,
                        "fit_type": None,
                        "touch_type": None,
                        "stretch_type": None,
                        "transparency_type": None,
                        "thickness_type": None,
                    }],
                },
            ),
            (
                "가을 데이트룩 코디 추천해줘. 20만원 이하로",
                {
                    "search_type": "coordination",
                    "total_budget": 200000,
                    "season_preferences": ["가을"],
                    "tpo_summary": "가을 데이트에 어울리는 캐주얼한 코디",
                    "slots": [
                        {
                            "category": "top",
                            "subcategory": None,
                            "clip_query_en": "casual autumn knit top",
                            "slot_budget": 55000,
                            "max_price": 71500,
                            "color": None,
                            "fit_type": None,
                            "touch_type": None,
                            "stretch_type": None,
                            "transparency_type": None,
                            "thickness_type": None,
                        },
                        {
                            "category": "bottom",
                            "subcategory": None,
                            "clip_query_en": "casual straight leg trousers",
                            "slot_budget": 60000,
                            "max_price": 78000,
                            "color": None,
                            "fit_type": None,
                            "touch_type": None,
                            "stretch_type": None,
                            "transparency_type": None,
                            "thickness_type": None,
                        },
                        {
                            "category": "shoes",
                            "subcategory": None,
                            "clip_query_en": "minimal casual sneakers",
                            "slot_budget": 85000,
                            "max_price": 110500,
                            "color": None,
                            "fit_type": None,
                            "touch_type": None,
                            "stretch_type": None,
                            "transparency_type": None,
                            "thickness_type": None,
                        },
                    ],
                },
            ),
            (
                "블레이저와 슬랙스만으로 코디해줘. 총 15만원 이하로",
                {
                    "search_type": "coordination",
                    "total_budget": 150000,
                    "season_preferences": ["봄", "가을"],
                    "tpo_summary": "블레이저와 슬랙스를 활용한 단정한 코디",
                    "slots": [
                        {
                            "category": "outer",
                            "subcategory": "슈트/블레이저 재킷",
                            "clip_query_en": "classic tailored blazer",
                            "slot_budget": 90000,
                            "max_price": 117000,
                            "color": None,
                            "fit_type": None,
                            "touch_type": None,
                            "stretch_type": None,
                            "transparency_type": None,
                            "thickness_type": None,
                        },
                        {
                            "category": "bottom",
                            "subcategory": "슈트 팬츠/슬랙스",
                            "clip_query_en": "classic tailored dress slacks",
                            "slot_budget": 60000,
                            "max_price": 78000,
                            "color": None,
                            "fit_type": None,
                            "touch_type": None,
                            "stretch_type": None,
                            "transparency_type": None,
                            "thickness_type": None,
                        },
                    ],
                },
            ),
        ]

        messages = [
            {
                "role": "system",
                "content": system_prompt,
            }
        ]

        for user_example, assistant_example in examples:
            messages.append({
                "role": "user",
                "content": user_example,
            })
            messages.append({
                "role": "assistant",
                "content": self._example_json(assistant_example),
            })

        messages.append({
            "role": "user",
            "content": user_query,
        })

        start_time = time.perf_counter() # 측정 시작

        completion = client.beta.chat.completions.parse(
            model=self.model_name,
            messages=messages,
            response_format=ParsedIntent
        )

        end_time = time.perf_counter()  # 측정 종료
        self.last_latency = end_time - start_time  # 소요 시간 저장 (초 단위)
        usage = getattr(completion, "usage", None)
        self.last_prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        self.last_completion_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        logger.debug(
            "QueryParser (%s) 응답 시간: %.4f초, tokens=(prompt=%d, completion=%d)",
            self.model_name,
            self.last_latency,
            self.last_prompt_tokens,
            self.last_completion_tokens,
        )

        parsed_intent = completion.choices[0].message.parsed

        if parsed_intent is None:
            raise ValueError("사용자 질의 파싱 결과가 비어 있습니다.")

        # 카테고리 및 예산에 대한 Python 보정은 수행하지 않는다.
        return parsed_intent
