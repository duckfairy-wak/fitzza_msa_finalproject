import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ==============================================================================
# [무신사 표준 실측 규격 정의 (FITZZA-53)]
# 상의/아우터, 하의, 신발, 모자 카테고리별 정확한 실측 항목
# ==============================================================================
# ==============================================================================
# [무신사 5대 표준 카테고리 실측 규격 정의]
# 서비스 전반의 표준에 맞춰 한글 대분류를 1급 기본 키(Primary Key)로 직접 사용합니다.
# ==============================================================================
MUSINSA_CATEGORY_SPEC_FIELDS: dict[str, list[str]] = {
    "상의": ["총장", "어깨너비", "가슴단면", "소매길이", "밑단단면", "소매부리단면", "암홀"],
    "아우터": ["총장", "어깨너비", "가슴단면", "소매길이", "밑단단면", "소매부리단면", "암홀"],
    "하의": ["총장", "허리단면", "엉덩이단면", "허벅지단면", "밑위", "밑단단면"],
    "신발": ["발길이", "발볼", "발목높이", "굽높이"],
    "모자": ["머리둘레", "챙길이", "깊이"],
}

# Qdrant 상품 payload(sizes[].measurements)는 데이터 파이프라인 vector_points.MEASUREMENT_KEYS의 영문 키로 저장된다.
# 이 맵이 어긋나면 모든 사이즈의 비교 항목이 0개가 되어 추천이 첫 사이즈·적합도 0%로 고정된다.
QDRANT_MEASUREMENT_KEY_TO_MUSINSA: dict[str, str] = {
    "top_length": "총장",
    "bottom_length": "총장",
    "shoulder": "어깨너비",
    "chest": "가슴단면",
    "sleeve": "소매길이",
    "top_hem": "밑단단면",
    "bottom_hem": "밑단단면",
    "cuff": "소매부리단면",
    "armhole": "암홀",
    "waist": "허리단면",
    "hip": "엉덩이단면",
    "thigh": "허벅지단면",
    "rise": "밑위",
    "foot_length": "발길이",
    "foot_width": "발볼",
    "ankle_height": "발목높이",
    "heel_height": "굽높이",
    "head_circumference": "머리둘레",
    "brim_length": "챙길이",
    "depth": "깊이",
}

# 하위 호환성을 위한 영문 보조 변환 맵 (안전장치)
_LEGACY_EN_TO_KO: dict[str, str] = {
    "top": "상의",
    "outer": "아우터",
    "bottom": "하의",
    "shoes": "신발",
    "hat": "모자",
}


def get_musinsa_spec_fields(category: str) -> list[str]:
    """카테고리(한글 기본)에 해당하는 무신사 표준 실측 항목 목록을 반환한다."""
    if not category:
        return []
    cat = category.strip()
    resolved_cat = _LEGACY_EN_TO_KO.get(cat.lower(), cat)
    return list(MUSINSA_CATEGORY_SPEC_FIELDS.get(resolved_cat, []))


def parse_numeric_measurement(raw_val: Any, is_shoes: bool = False) -> Optional[float]:
    """
    실측 수치를 float로 변환하고, 신발의 경우 cm 입력 시 mm로 자동 변환한다.
    - 일반 의류(상의/하의/모자): cm 단위 기준
    - 신발(shoes): mm 단위 기준 (20~35 사이 수치가 들어오면 cm로 판단하여 * 10)
    """
    if raw_val is None:
        return None

    try:
        if isinstance(raw_val, str):
            cleaned = raw_val.strip().lower().replace("cm", "").replace("mm", "").strip()
            val = float(cleaned)
        else:
            val = float(raw_val)
    except (ValueError, TypeError):
        return None

    if val <= 0:
        return None

    # 신발의 경우 20~35 범위(예: 26, 26.5)는 cm 표기이므로 mm(260, 265)로 자동 환산
    if is_shoes and 20.0 <= val <= 35.0:
        val *= 10.0

    return round(val, 1)


def normalize_measurement_spec(
    raw_spec: Optional[dict[str, Any]],
    category: Optional[str] = None
) -> dict[str, float]:
    """
    무신사 크롤링 데이터 기준 실측 스펙 정규화 함수:
    - Qdrant payload 영문 키(top_length 등)는 무신사 표준 한글 필드로 변환
    - 지정된 카테고리의 무신사 표준 필드만 추출
    - 수치 파싱 및 신발(cm/mm) 단위 보정
    """
    if not raw_spec or not isinstance(raw_spec, dict):
        return {}

    cat = category.strip() if category else ""
    resolved_cat = _LEGACY_EN_TO_KO.get(cat.lower(), cat) if cat else None
    target_fields = MUSINSA_CATEGORY_SPEC_FIELDS.get(resolved_cat) if resolved_cat else None
    is_shoes = (resolved_cat == "신발")

    normalized: dict[str, float] = {}

    for field, raw_val in raw_spec.items():
        if not field:
            continue
        clean_field = str(field).strip()
        clean_field = QDRANT_MEASUREMENT_KEY_TO_MUSINSA.get(clean_field, clean_field)

        # 카테고리가 지정된 경우 해당 카테고리의 무신사 표준 필드만 허용
        if target_fields is not None and clean_field not in target_fields:
            continue

        parsed_val = parse_numeric_measurement(raw_val, is_shoes=is_shoes)
        if parsed_val is not None:
            normalized[clean_field] = parsed_val

    return normalized


class MusinsaSizeSpecResolver:
    """무신사 표준 실측 스펙 조회 및 검증 서비스"""

    @classmethod
    def get_supported_categories(cls) -> list[str]:
        """지원하는 카테고리 목록을 반환한다."""
        return list(MUSINSA_CATEGORY_SPEC_FIELDS.keys())

    @classmethod
    def get_spec_fields(cls, category: str) -> list[str]:
        """카테고리에 해당하는 무신사 표준 실측 항목을 반환한다."""
        return get_musinsa_spec_fields(category)

    @classmethod
    def normalize(cls, raw_spec: dict[str, Any], category: Optional[str] = None) -> dict[str, float]:
        """실측 스펙 데이터를 무신사 표준 규격으로 정규화한다."""
        return normalize_measurement_spec(raw_spec, category=category)
