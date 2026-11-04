import inspect
import json
import logging
import os
import re
import threading
import time
from typing import Any, Optional

from app.services.size_spec_normalizer import (
    MUSINSA_CATEGORY_SPEC_FIELDS,
    get_musinsa_spec_fields,
    normalize_measurement_spec,
    MusinsaSizeSpecResolver,
)

logger = logging.getLogger(__name__)
_MOCK_DB_LOCK = threading.Lock()

# AWS S3 3,000개 상품 JSON 전수 조사 및 무신사 공식 물성 스펙(features['핏'], fit_type) 기반 정규화 매핑 테이블
MUSINSA_CANONICAL_FITS: dict[str, str] = {
    # 1. 오버 사이즈 - 무신사 공식 표기: '오버 사이즈'
    "오버 사이즈": "오버 사이즈",
    "오버사이즈": "오버 사이즈",
    "오버핏": "오버 사이즈",
    "오버": "오버 사이즈",

    # 2. 루즈 - 무신사 공식 표기: '루즈'
    "루즈": "루즈",
    "루즈핏": "루즈",
    "릴렉스드": "루즈",
    "릴렉스": "루즈",

    # 3. 레귤러 - 무신사 공식 표기: '레귤러'
    "레귤러": "레귤러",
    "레귤러핏": "레귤러",
    "스탠다드": "레귤러",
    "스탠다드핏": "레귤러",
    "기본": "레귤러",
    "기본핏": "레귤러",

    # 4. 슬림 - 무신사 공식 표기: '슬림'
    "슬림": "슬림",
    "슬림핏": "슬림",

    # 5. 스키니 - 무신사 공식 표기: '스키니'
    "스키니": "스키니",
    "스키니핏": "스키니",

    # 6. 와이드 (하의/바지 전용) -> 무신사 실데이터 물성 기준 '루즈'로 수렴
    "와이드": "루즈",
    "와이드핏": "루즈",
    "세미와이드": "루즈",
    "세미와이드핏": "루즈",
    "스트레이트": "레귤러",
    "테이퍼드": "테이퍼드",
}


def normalize_fit_name(fit: Optional[str]) -> str:
    """무신사 공식 데이터 스키마(features['핏']) 기준 표준 핏 명칭으로 정규화한다."""
    if not fit:
        return ""
    cleaned = str(fit).strip().lower()
    if cleaned in MUSINSA_CANONICAL_FITS:
        return MUSINSA_CANONICAL_FITS[cleaned]
    # '핏' 접미사 또는 공백 제거 후 재조회
    simplified = str(fit).strip().replace(" ", "").replace("핏", "").lower()
    if simplified in MUSINSA_CANONICAL_FITS:
        return MUSINSA_CANONICAL_FITS[simplified]
    return simplified


def is_fit_match(target_fit: Optional[str], candidate_fit: Optional[str]) -> bool:
    """정규화된 두 핏 명칭이 일치하는지 비교한다."""
    norm_target = normalize_fit_name(target_fit)
    norm_cand = normalize_fit_name(candidate_fit)
    if not norm_target or not norm_cand:
        return False
    return norm_target == norm_cand


def is_general_fit(fit: Optional[str]) -> bool:
    """일반/기본/레귤러 핏인지 판별한다."""
    norm = normalize_fit_name(fit)
    return norm in ("", "레귤러")


class SizeProfileResolver:
    def __init__(self, data_path: Optional[str] = None, enable_mock_data: Optional[bool] = None):
        """사이즈 프로필 리졸버를 초기화하고 설정에 따라 개발용 Mock 데이터를 로드한다."""
        explicit_data_path = data_path is not None
        if data_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            data_path = os.path.abspath(os.path.join(base_dir, "../../data/mock_size_data.json"))

        if enable_mock_data is None:
            from app.core.config import get_settings

            enable_mock_data = bool(
                explicit_data_path
                or get_settings().enable_dev_mock_size_data
                or os.environ.get("PYTEST_CURRENT_TEST")
            )

        self.data_path = data_path
        self.enable_mock_data = enable_mock_data
        self._load_mock_data()
        self.last_resolve_latency: float = 0.0
        self.last_calc_latency: float = 0.0
        self.last_total_latency: float = 0.0

    def reset_latencies(self) -> None:
        """측정된 사이즈 추천 지연 시간 지표를 0으로 초기화한다."""
        self.last_resolve_latency = 0.0
        self.last_calc_latency = 0.0
        self.last_total_latency: float = 0.0

    def _load_mock_data(self):
        """로컬/개발/테스트 전용 Mock JSON 데이터를 메모리에 로드한다 (운영 환경에서는 비활성화)."""
        if not self.enable_mock_data:
            self.mock_db = {
                "users": [],
                "user_preferences": [],
                "orders_and_surveys": [],
                "other_users_fits": []
            }
            return

        if os.path.exists(self.data_path):
            with open(self.data_path, "r", encoding="utf-8") as f:
                self.mock_db = json.load(f)
            logger.info("[SizeProfileResolver] Mock 데이터 로드 성공: %s", self.data_path)
        else:
            logger.warning("[SizeProfileResolver 경고] Mock 데이터 파일을 찾을 수 없습니다: %s", self.data_path)
            self.mock_db = {
                "users": [],
                "user_preferences": [],
                "orders_and_surveys": [],
                "other_users_fits": []
            }

    def resolve_and_calculate_size(
            self,
            user_id: str,
            subcategory: str,
            fit_type: str,
            candidate_products: list[dict[str, Any]],
            category_type: str,
            user_body: Optional[dict[str, Any]] = None,
            learned_preference: Optional[dict[str, float]] = None,
    ) -> dict[str, Any]:
        """
        [1. 추천 진입점]
        우선순위 체인을 타서 가장 신뢰도 높은 베이스라인(기준 치수)을 확보한 뒤,
        SizeCalculator를 통해 최적의 사이즈를 도출한다.
        """
        start_total = time.perf_counter()
        start_resolve = time.perf_counter()
        baseline_spec = self._get_baseline_spec(
            user_id,
            subcategory,
            fit_type,
            category_type=category_type,
            user_body=user_body,
            learned_preference=learned_preference,
        )
        self.last_resolve_latency += (time.perf_counter() - start_resolve)

        if not baseline_spec or baseline_spec["data"] is None:
            self.last_total_latency += (time.perf_counter() - start_total)
            return {
                "source_type": "none",
                "baseline_spec": None,
                "recommendation": None
            }

        start_calc = time.perf_counter()
        recommended_result = SizeCalculator.evaluate(
            candidate_products=candidate_products,
            baseline_spec=baseline_spec["data"],
            category_type=category_type
        )
        self.last_calc_latency += (time.perf_counter() - start_calc)
        self.last_total_latency += (time.perf_counter() - start_total)

        return {
            "source_type": baseline_spec["source"],
            "baseline_spec": baseline_spec["data"],
            "recommendation": recommended_result
        }

    def _get_baseline_spec(
            self,
            user_id: str,
            subcategory: str,
            fit_type: str,
            category_type: Optional[str] = None,
            user_body: Optional[dict[str, Any]] = None,
            learned_preference: Optional[dict[str, float]] = None,
    ) -> dict[str, Any]:
        """
        [2. 우선순위 체인 (Fallback Chain) 라우팅 - 핏 우선 2단계 탐색]

        1단계. 요청 핏('슬림', '와이드', '오버사이즈' 등) 조건 충족 데이터 최우선 탐색
           ├─ ① 내 요청 핏 선호 실측 (내 데이터 + 요청 핏) ➔ 1순위
           ├─ ② 내 최근 구매한 요청 핏 상품 실측 (내 구매이력 + 요청 핏) ➔ 2순위
           └─ ③ 키·몸무게 유사 체형의 요청 핏 인증 실측 (유사체형 + 요청 핏) ➔ 3순위 (핏 유지!)

        2단계. 위 3가지 모두 없을 때 (또는 특정 핏 요청이 없을 때) 일반 핏으로 폴백 (Fallback)
           ├─ ④ 내 레귤러/기본 선호 실측 (외부 learned_preference 포함) ➔ 4순위
           ├─ ⑤ 내 일반 구매 이력 실측 ➔ 5순위
           ├─ (신발): 사용자 등록 신발 사이즈 직접 반영 (body_profile)
           └─ ⑥ 유사 체형의 일반 실측 ➔ 6순위
        """
        target_fit = normalize_fit_name(fit_type)
        has_specific_fit = bool(target_fit and not is_general_fit(fit_type))

        # 사용자 신체 프로필 파싱 (키, 몸무게, 발사이즈)
        # 의류는 키/몸무게(t_height, t_weight)를 사용하고, 신발은 발사이즈(shoe_size)를 독립적으로 사용하므로
        # 키/몸무게가 없다고 해서 전달된 프로필(shoe_size 포함)을 버리지 않는다.
        target_user = None
        if user_body is not None and isinstance(user_body, dict):
            target_user = parse_user_body(user_body)
        stored_user = next(
            (u for u in self.mock_db.get("users", []) if str(u.get("user_id")) == str(user_id)),
            None
        )
        if target_user is None:
            target_user = stored_user
        elif stored_user and target_user.get("height") is None and target_user.get("weight") is None:
            target_user = {**stored_user, **target_user}

        t_height: Optional[float] = None
        t_weight: Optional[float] = None
        if target_user:
            try:
                if target_user.get("height") is not None:
                    t_height = float(target_user["height"])
                if target_user.get("weight") is not None:
                    t_weight = float(target_user["weight"])
            except (TypeError, ValueError):
                t_height = None
                t_weight = None

        # =========================================================================
        # 1단계. 요청 핏 조건 충족 데이터 최우선 탐색 (특정 핏 요청이 있는 경우)
        # =========================================================================
        if has_specific_fit:
            # ① 내 요청 핏 선호 실측 (내 데이터 + 요청 핏) ➔ 1순위
            for pref in self.mock_db.get("user_preferences", []):
                if (
                    str(pref.get("user_id")) == str(user_id)
                    and pref.get("subcategory") == subcategory
                    and is_fit_match(target_fit, pref.get("fit_type"))
                    and pref.get("preference_spec")
                ):
                    return {
                        "source": "learned_preference",
                        "data": pref.get("preference_spec"),
                    }

            # ② 내 최근 구매한 요청 핏 상품 실측 (내 구매이력 + 요청 핏) ➔ 2순위
            for order in self.mock_db.get("orders_and_surveys", []):
                if (
                    str(order.get("user_id")) == str(user_id)
                    and order.get("subcategory") == subcategory
                    and is_fit_match(target_fit, order.get("fit_type"))
                    and order.get("measurement_spec")
                ):
                    return {
                        "source": "recent_purchase",
                        "data": order.get("measurement_spec"),
                    }

            # ③ 키·몸무게 유사 체형의 요청 핏 인증 실측 (유사체형 + 요청 핏) ➔ 3순위 (핏 유지!)
            if t_height is not None and t_weight is not None:
                for other in self.mock_db.get("other_users_fits", []):
                    if (
                        other.get("subcategory") == subcategory
                        and is_fit_match(target_fit, other.get("fit_type"))
                        and other.get("measurement_spec")
                    ):
                        try:
                            o_height = float(other.get("height", 0))
                            o_weight = float(other.get("weight", 0))
                        except (TypeError, ValueError):
                            continue

                        if abs(t_height - o_height) <= 3.0 and abs(t_weight - o_weight) <= 4.0:
                            return {
                                "source": "similar_body_profile",
                                "data": other.get("measurement_spec"),
                            }

        # =========================================================================
        # 2단계. 위 3가지 모두 없거나 일반 핏일 때: 일반 핏으로 폴백 (Fallback)
        # =========================================================================
        # ④ 내 레귤러/기본 선호 실측
        if learned_preference:
            return {
                "source": "learned_preference",
                "data": dict(learned_preference),
            }

        user_prefs = [
            p for p in self.mock_db.get("user_preferences", [])
            if str(p.get("user_id")) == str(user_id)
            and p.get("subcategory") == subcategory
            and p.get("preference_spec")
        ]
        if user_prefs:
            best_pref = next(
                (p for p in user_prefs if is_general_fit(p.get("fit_type"))),
                user_prefs[0]
            )
            return {
                "source": "learned_preference",
                "data": best_pref.get("preference_spec"),
            }

        # ⑤ 내 일반 구매 이력 실측
        user_orders = [
            o for o in self.mock_db.get("orders_and_surveys", [])
            if str(o.get("user_id")) == str(user_id)
            and o.get("subcategory") == subcategory
            and o.get("measurement_spec")
        ]
        if user_orders:
            best_order = next(
                (o for o in user_orders if is_general_fit(o.get("fit_type"))),
                user_orders[0]
            )
            return {
                "source": "recent_purchase",
                "data": best_order.get("measurement_spec"),
            }

        # 신발 특화: 유저 등록 shoeSize를 발길이 기준 치수로 반영
        if category_type in ("shoes", "신발") and target_user and target_user.get("shoe_size"):
            try:
                shoe_val = float(target_user["shoe_size"])
                if shoe_val < 50.0:
                    shoe_val *= 10.0
                return {
                    "source": "body_profile",
                    "data": {
                        "발길이": shoe_val,
                        "shoe_size": shoe_val,
                    }
                }
            except (ValueError, TypeError):
                pass

        # ⑥ 유사 체형의 일반 실측
        if t_height is not None and t_weight is not None:
            similar_others = []
            for other in self.mock_db.get("other_users_fits", []):
                if (
                    other.get("subcategory") == subcategory
                    and other.get("measurement_spec")
                ):
                    try:
                        o_height = float(other.get("height", 0))
                        o_weight = float(other.get("weight", 0))
                    except (TypeError, ValueError):
                        continue

                    if abs(t_height - o_height) <= 3.0 and abs(t_weight - o_weight) <= 4.0:
                        similar_others.append(other)

            if similar_others:
                best_other = next(
                    (o for o in similar_others if is_general_fit(o.get("fit_type"))),
                    similar_others[0]
                )
                return {
                    "source": "similar_body_profile",
                    "data": best_other.get("measurement_spec"),
                }

        return {
            "source": "none",
            "data": None,
        }

    def update_fit_preferences(self, user_id: str, subcategory: str, fit_type: str, purchased_size_spec: dict):
        """
        [3. Closed-Loop 학습 루프]
        설문에서 "FIT(잘 맞아요)" 응답 시 누적 이동 평균으로 선호 실측 갱신.
        """
        with _MOCK_DB_LOCK:
            prefs = self.mock_db.setdefault("user_preferences", [])
            existing = next(
                (
                    p for p in prefs
                    if str(p.get("user_id")) == str(user_id)
                    and p.get("subcategory") == subcategory
                    and is_fit_match(fit_type, p.get("fit_type"))
                ),
                None
            )
            if existing is None and is_general_fit(fit_type):
                existing = next(
                    (
                        p for p in prefs
                        if str(p.get("user_id")) == str(user_id)
                        and p.get("subcategory") == subcategory
                        and is_general_fit(p.get("fit_type"))
                    ),
                    None
                )

            if not existing:
                new_pref = {
                    "preference_id": len(prefs) + 1,
                    "user_id": user_id,
                    "subcategory": subcategory,
                    "fit_type": fit_type,
                    "preference_spec": purchased_size_spec,
                    "sample_count": 1
                }
                prefs.append(new_pref)
            else:
                n = existing.get("sample_count", 1)
                spec = existing.get("preference_spec", {})
                updated_spec = {}

                for key, val in purchased_size_spec.items():
                    if key in spec and spec[key] is not None and val is not None:
                        updated_spec[key] = round((spec[key] * n + val) / (n + 1), 1)
                    else:
                        updated_spec[key] = val if val is not None else spec.get(key)

                existing["preference_spec"] = updated_spec
                existing["sample_count"] = n + 1


class SizeCalculator:
    @staticmethod
    def evaluate(candidate_products: list[dict[str, Any]], baseline_spec: dict[str, float], category_type: str) -> Optional[dict[str, Any]]:
        """
        [4. 수학적 산출 엔진]
        상품 실측과 기준 치수를 비교하여 오차가 가장 적은 최적의 상품과 사이즈를 도출한다.
        """
        if not baseline_spec or not candidate_products:
            return None

        best_match = None
        min_penalty = float('inf')

        fields = get_musinsa_spec_fields(category_type)
        if not fields:
            return None

        normalized_baseline = normalize_measurement_spec(baseline_spec, category=category_type)

        for product in candidate_products:
            sizes = product.get("sizes")
            if not sizes:
                continue

            for size_option in sizes:
                penalty = 0.0
                valid_fields_count = 0

                raw_measurements = size_option.get("measurements", {})
                measurements = normalize_measurement_spec(raw_measurements, category=category_type)

                for field in fields:
                    meas_val = measurements.get(field)
                    base_val = normalized_baseline.get(field)

                    if (
                            meas_val is not None and isinstance(meas_val, (int, float)) and meas_val > 0 and
                            base_val is not None and isinstance(base_val, (int, float)) and base_val > 0
                    ):
                        penalty += abs(meas_val - base_val)
                        valid_fields_count += 1

                if valid_fields_count == 0:
                    # 신발 특화: 상세 실측표가 없고 표기 사이즈(260, 265 등)만 제공되는 상품의 라벨 직접 매칭
                    if category_type in ("shoes", "신발"):
                        user_shoe = (
                            baseline_spec.get("shoe_size")
                            or baseline_spec.get("발길이")
                            or normalized_baseline.get("발길이")
                        )
                        if user_shoe:
                            m = re.search(r"\d+(?:\.\d+)?", str(size_option.get("size", "")))
                            if m:
                                try:
                                    opt_shoe = float(m.group())
                                    if opt_shoe < 50.0:
                                        opt_shoe *= 10.0
                                    diff = abs(opt_shoe - float(user_shoe))
                                    penalty = diff * 0.8
                                    valid_fields_count = 1
                                    fit_score = max(0.0, 1.0 - (diff / 33.3))
                                except (ValueError, TypeError):
                                    pass
                    if valid_fields_count == 0:
                        fit_score = 0.0
                elif penalty > 25.0:
                    fit_score = 0.0
                else:
                    fit_score = max(0.0, 1.0 - (penalty / 25.0))

                if penalty < min_penalty:
                    min_penalty = penalty
                    best_match = {
                        "product_id": product.get("product_id"),
                        "product_name": product.get("product_name"),
                        "size_label": size_option.get("size", "Unknown"),
                        "predicted_fit_score": round(fit_score, 2)
                    }

        return best_match


FIT_SOURCE_EVIDENCE_MAP: dict[str, str] = {
    "learned_preference": "기존 구매·설문 기반 선호 실측과 가장 유사한 사이즈입니다.",
    "recent_purchase": "최근 구매하신 상품 실측을 기준으로 추천된 사이즈입니다.",
    "similar_body_profile": "유사 체형 사용자의 실측 데이터를 기준으로 추천된 사이즈입니다.",
    "body_profile": "등록하신 사용자 신체 프로필 정보를 기준으로 추천된 사이즈입니다.",
}


def parse_user_body(user_body: dict[str, Any] | None) -> dict[str, float] | None:
    """사용자 신체 프로필 딕셔너리에서 키, 몸무게, 발 사이즈를 추출해 float 딕셔너리로 정규화한다."""
    if not user_body or not isinstance(user_body, dict):
        return None
    raw_height = user_body.get("height")
    raw_weight = user_body.get("weight")
    raw_shoe = user_body.get("shoeSize") if "shoeSize" in user_body else user_body.get("shoe_size")

    try:
        height = float(raw_height) if raw_height is not None else None
    except (TypeError, ValueError):
        height = None

    try:
        weight = float(raw_weight) if raw_weight is not None else None
    except (TypeError, ValueError):
        weight = None

    try:
        shoe_size = float(raw_shoe) if raw_shoe is not None else None
    except (TypeError, ValueError):
        shoe_size = None

    if height is None and weight is None and shoe_size is None:
        return None

    parsed: dict[str, float] = {}
    if height is not None:
        parsed["height"] = height
    if weight is not None:
        parsed["weight"] = weight
    if shoe_size is not None:
        parsed["shoe_size"] = shoe_size
    return parsed


def sync_user_body(
    size_resolver: Any,
    user_id: str,
    user_body: dict[str, Any] | None,
) -> None:
    """사용자 신체 치수 정보를 리졸버 내부 메모리 저장소에 동기화한다."""
    if size_resolver is None:
        return
    parsed = parse_user_body(user_body)
    if parsed is None:
        return

    mock_db = getattr(size_resolver, "mock_db", None)
    if not isinstance(mock_db, dict):
        return

    with _MOCK_DB_LOCK:
        users = mock_db.setdefault("users", [])
        existing = next(
            (u for u in users if str(u.get("user_id")) == str(user_id)),
            None,
        )
        if existing is None:
            entry: dict[str, Any] = {"user_id": str(user_id), **parsed}
            users.append(entry)
        else:
            existing.update(parsed)


def sync_user_size_preference(
    size_resolver: Any,
    user_id: str,
    subcategory: str | None,
    fit_type: str | None,
    pref_spec: dict[str, float] | None,
) -> None:
    """사용자의 서브카테고리 및 핏별 선호 실측 데이터를 리졸버 내부 저장소에 동기화한다."""
    if size_resolver is None or not subcategory or not pref_spec:
        return
    mock_db = getattr(size_resolver, "mock_db", None)
    if not isinstance(mock_db, dict):
        return

    target_fit = fit_type or "레귤러"
    with _MOCK_DB_LOCK:
        prefs = mock_db.setdefault("user_preferences", [])
        existing = next(
            (
                p
                for p in prefs
                if str(p.get("user_id")) == str(user_id)
                and p.get("subcategory") == subcategory
                and is_fit_match(target_fit, p.get("fit_type"))
            ),
            None,
        )
        if existing is None and is_general_fit(target_fit):
            existing = next(
                (
                    p
                    for p in prefs
                    if str(p.get("user_id")) == str(user_id)
                    and p.get("subcategory") == subcategory
                    and is_general_fit(p.get("fit_type"))
                ),
                None,
            )

        if existing is None:
            prefs.append(
                {
                    "preference_id": len(prefs) + 1,
                    "user_id": str(user_id),
                    "subcategory": subcategory,
                    "fit_type": target_fit,
                    "preference_spec": dict(pref_spec),
                    "sample_count": 1,
                }
            )
        else:
            existing["preference_spec"] = dict(pref_spec)
            if fit_type:
                existing["fit_type"] = fit_type


def infer_category_from_measurements(sizes: list[dict[str, Any]]) -> str:
    """상품 사이즈별 실측 키 목록으로부터 대분류 카테고리(상의/하의/신발/모자)를 추론한다."""
    for entry in sizes:
        if not isinstance(entry, dict):
            continue
        measurements = entry.get("measurements") or {}
        if not isinstance(measurements, dict):
            continue
        keys = set(measurements.keys())
        if keys.intersection({"허리단면", "엉덩이단면", "허벅지단면", "밑위"}):
            return "하의"
        if keys.intersection({"발길이", "발볼", "발목높이", "굽높이"}):
            return "신발"
        if keys.intersection({"머리둘레", "챙길이", "깊이"}):
            return "모자"
    return "상의"


def extract_payload_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Qdrant 상품 페이로드에서 상품명, 카테고리, 서브카테고리, 핏, 사이즈 목록을 추출한다."""
    product_name = str(payload.get("product_name") or "")
    raw_category = str(payload.get("category") or "").strip()
    raw_subcategory = str(payload.get("subcategory") or "").strip()
    subcategory: str | None = raw_subcategory if raw_subcategory else None
    fit_type = "레귤러"

    features = payload.get("features")
    if isinstance(features, dict):
        fit_val = features.get("핏")
        if isinstance(fit_val, list) and fit_val:
            fit_type = str(fit_val[0]).strip() or "레귤러"
        elif isinstance(fit_val, str) and fit_val.strip():
            fit_type = fit_val.strip()
    elif payload.get("fit_type"):
        fit_type = str(payload.get("fit_type")).strip()

    raw_sizes: list[dict[str, Any]] = []
    qdrant_sizes = payload.get("sizes")
    if isinstance(qdrant_sizes, list):
        for s in qdrant_sizes:
            if isinstance(s, dict):
                raw_sizes.append(s)

    return {
        "product_name": product_name,
        "raw_category": raw_category,
        "subcategory": subcategory,
        "fit_type": fit_type,
        "sizes": raw_sizes,
    }


def fetch_qdrant_product_payload(
    qdrant_client: Any,
    collection_name: str,
    product_id: int,
) -> dict[str, Any] | None:
    """Qdrant 컬렉션에서 지정된 product_id의 상품 페이로드를 조회한다."""
    if qdrant_client is None:
        return None
    try:
        from qdrant_client.http import models

        scroll_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="product_id",
                    match=models.MatchValue(value=int(product_id)),
                )
            ]
        )
        points, _ = qdrant_client.scroll(
            collection_name=collection_name,
            scroll_filter=scroll_filter,
            with_payload=True,
            with_vectors=False,
            limit=1,
        )
        if points and points[0].payload:
            return dict(points[0].payload)
    except Exception as exc:
        logger.warning("Qdrant 상품 페이로드 조회 실패 (productId=%s): %s", product_id, exc)
    return None


def resolve_product_for_size(
    product_id: int,
    qdrant_client: Any,
    collection_name: str,
    product_client: Any = None,
    request_id_header: str | None = None,
) -> dict[str, Any] | None:
    """Qdrant 및 product-service를 조회하여 사이즈 추천에 필요한 상품 메타데이터와 실측표를 반환한다."""
    payload = fetch_qdrant_product_payload(
        qdrant_client=qdrant_client,
        collection_name=collection_name,
        product_id=product_id,
    )
    raw_sizes: list[dict[str, Any]] = []
    raw_category = ""
    subcategory: str | None = None
    fit_type = "레귤러"
    product_name = ""

    if payload is not None:
        meta = extract_payload_metadata(payload)
        product_name = meta["product_name"]
        raw_category = meta["raw_category"]
        subcategory = meta["subcategory"]
        fit_type = meta["fit_type"]
        raw_sizes = meta["sizes"]

    if not raw_sizes and product_client is not None and hasattr(product_client, "get_product_measurements"):
        try:
            measurements_map = product_client.get_product_measurements(
                [product_id],
                request_id_header=request_id_header,
            )
        except Exception as exc:
            logger.warning("product-service 실측 조회 실패 (productId=%s): %s", product_id, exc)
            measurements_map = {}

        if isinstance(measurements_map, dict) and product_id in measurements_map:
            seen_size_labels: set[str] = set()
            for opt in measurements_map.get(product_id) or []:
                if not isinstance(opt, dict):
                    continue
                size_label = str(opt.get("size") or "FREE").strip()
                if size_label in seen_size_labels:
                    continue
                seen_size_labels.add(size_label)
                raw_sizes.append(
                    {
                        "size": size_label,
                        "measurements": opt.get("measurements") or {},
                    }
                )

    if payload is None and not raw_sizes:
        return None

    category_type = raw_category or infer_category_from_measurements(raw_sizes)

    return {
        "product_id": product_id,
        "product_name": product_name,
        "category_type": category_type,
        "subcategory": subcategory,
        "fit_type": fit_type,
        "sizes": raw_sizes,
    }


def evaluate_single_product_size(
    size_resolver: Any,
    repository: Any,
    user_client: Any,
    user_id: int,
    product_data: dict[str, Any],
    request_id_header: str | None = None,
) -> dict[str, Any]:
    """단일 상품에 대해 사용자 선호 실측 및 신체 정보를 바탕으로 추천 사이즈와 적합도(%)를 산출한다."""
    raw_sizes = product_data.get("sizes") or []
    if not raw_sizes:
        return {
            "recommendedSize": None,
            "fitPercent": None,
            "evidence": "해당 상품의 상세 실측 정보가 없어 사이즈 추천을 제공할 수 없습니다.",
        }

    size_labels = [
        str(s.get("size")).strip()
        for s in raw_sizes
        if isinstance(s, dict) and s.get("size") is not None and str(s.get("size")).strip()
    ]
    if (
        len(size_labels) == 1
        and size_labels[0].upper() in {"FREE", "ONE SIZE", "ONESIZE"}
    ):
        return {
            "recommendedSize": None,
            "fitPercent": None,
            "evidence": "단일 사이즈(FREE)로 제공되는 상품입니다.",
        }

    subcategory: str | None = product_data.get("subcategory")
    fit_type = str(product_data.get("fit_type") or "레귤러")
    category_type = str(product_data.get("category_type") or "상의")

    db_pref: dict[str, float] | None = None
    if subcategory and repository is not None:
        try:
            db_pref = repository.get_user_size_preference(
                user_id=user_id,
                subcategory=subcategory,
            )
        except Exception as exc:
            logger.warning(
                "선호 실측 DB 조회 실패 (userId=%s, subcategory=%s): %s",
                user_id,
                subcategory,
                exc,
            )

    user_body: dict[str, Any] | None = None
    if not db_pref:
        if user_client is not None:
            try:
                user_body = user_client.get_user_body(
                    user_id=user_id,
                    request_id_header=request_id_header,
                )
            except Exception as exc:
                logger.warning("user-service 신체 정보 조회 실패 (userId=%s): %s", user_id, exc)
                user_body = {}
        else:
            user_body = {}

    resolve_fn = size_resolver.resolve_and_calculate_size
    sig_params = inspect.signature(resolve_fn).parameters
    resolve_kwargs: dict[str, Any] = {
        "user_id": str(user_id),
        "subcategory": subcategory or "",
        "fit_type": fit_type,
        "candidate_products": [product_data],
        "category_type": category_type,
    }
    if "user_body" in sig_params or any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig_params.values()
    ):
        resolve_kwargs["user_body"] = user_body
        resolve_kwargs["learned_preference"] = db_pref
    else:
        sync_user_body(
            size_resolver=size_resolver,
            user_id=str(user_id),
            user_body=user_body,
        )
        sync_user_size_preference(
            size_resolver=size_resolver,
            user_id=str(user_id),
            subcategory=subcategory,
            fit_type=fit_type,
            pref_spec=db_pref,
        )

    size_result = resolve_fn(**resolve_kwargs)

    source_type = str(size_result.get("source_type") or "none")
    baseline_spec = size_result.get("baseline_spec")
    recommendation = size_result.get("recommendation")

    if source_type == "none" or baseline_spec is None:
        return {
            "recommendedSize": None,
            "fitPercent": None,
            "evidence": "체형 정보를 등록하시면 맞춤 사이즈를 추천해 드립니다.",
        }

    if not recommendation or not recommendation.get("size_label"):
        return {
            "recommendedSize": None,
            "fitPercent": None,
            "evidence": "해당 상품의 상세 실측 정보가 없어 사이즈 추천을 제공할 수 없습니다.",
        }

    raw_fit_score = float(recommendation.get("predicted_fit_score") or 0.0)
    fit_percent = round(
        raw_fit_score * 100.0 if raw_fit_score <= 1.0 else raw_fit_score,
        1,
    )
    fit_percent = max(0.0, min(100.0, fit_percent))

    return {
        "recommendedSize": str(recommendation["size_label"]),
        "fitPercent": fit_percent,
        "evidence": FIT_SOURCE_EVIDENCE_MAP.get(source_type),
    }


def process_size_feedback(
    user_id: int,
    product_id: int,
    option_id: int,
    size_feedback: str,
    repository: Any,
    product_client: Any,
    qdrant_payload: dict[str, Any] | None = None,
    size_resolver: Any = None,
    cache_service: Any = None,
    request_id_header: str | None = None,
) -> None:
    """사용자의 구매 후 사이즈 피드백을 저장하고 선호 실측 프로필을 갱신한다."""
    purchased_spec: dict[str, float] | None = None
    if product_client is not None and hasattr(product_client, "find_option_measurement"):
        try:
            purchased_spec = product_client.find_option_measurement(
                product_id=product_id,
                option_id=option_id,
                request_id_header=request_id_header,
            )
        except Exception as exc:
            logger.warning(
                "옵션 실측 조회 실패 (productId=%s, optionId=%s): %s",
                product_id,
                option_id,
                exc,
            )

    subcategory: str | None = None
    fit_type: str | None = None
    if qdrant_payload is not None:
        meta = extract_payload_metadata(qdrant_payload)
        subcategory = meta["subcategory"] or None
        fit_type = meta["fit_type"] or None

    repository.save_size_feedback(
        user_id=user_id,
        product_id=product_id,
        option_id=option_id,
        size_feedback=size_feedback,
        subcategory=subcategory,
        fit_type=fit_type,
        purchased_spec=purchased_spec,
    )

    if subcategory and size_resolver is not None:
        try:
            updated_pref = repository.get_user_size_preference(
                user_id=user_id,
                subcategory=subcategory,
            )
            sync_user_size_preference(
                size_resolver=size_resolver,
                user_id=str(user_id),
                subcategory=subcategory,
                fit_type=fit_type or "레귤러",
                pref_spec=updated_pref,
            )
        except Exception as exc:
            logger.warning("선호 실측 동기화 실패 (userId=%s): %s", user_id, exc)

    if cache_service is not None and hasattr(cache_service, "invalidate_user_pipeline"):
        cache_service.invalidate_user_pipeline(user_id=str(user_id))
