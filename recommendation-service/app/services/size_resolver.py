import inspect
import json
import logging
import os
import re
import threading
from typing import Any, Optional

from app.services.size_spec_normalizer import (
    MUSINSA_CATEGORY_SPEC_FIELDS,
    get_musinsa_spec_fields,
    normalize_measurement_spec,
    MusinsaSizeSpecResolver,
)

logger = logging.getLogger(__name__)
_MOCK_DB_LOCK = threading.Lock()


class SizeProfileResolver:
    def __init__(self, data_path: Optional[str] = None):
        if data_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            data_path = os.path.abspath(os.path.join(base_dir, "../../data/mock_size_data.json"))

        self.data_path = data_path
        self._load_mock_data()

    def _load_mock_data(self):
        """테스트용 Mock JSON 데이터를 메모리에 로드한다."""
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
        baseline_spec = self._get_baseline_spec(
            user_id,
            subcategory,
            fit_type,
            category_type=category_type,
            user_body=user_body,
            learned_preference=learned_preference,
        )

        if not baseline_spec or baseline_spec["data"] is None:
            return {
                "source_type": "none",
                "baseline_spec": None,
                "recommendation": None
            }

        recommended_result = SizeCalculator.evaluate(
            candidate_products=candidate_products,
            baseline_spec=baseline_spec["data"],
            category_type=category_type
        )

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
        [2. 우선순위 체인 (Fallback Chain) 라우팅]
        1순위: 선호 실측 (learned_preference)
        2순위: 최근 구매 이력 실측 (recent_purchase)
        3순위 (신발): 사용자 등록 신발 사이즈 직접 반영 (body_profile)
        3순위 (의류): 키/몸무게 기반 비슷한 체형 타 사용자 인증 데이터 (similar_body_profile)
        """
        # 1순위: 요청 스코프 또는 mock_db에서 선호 실측 탐색 (subcategory 매칭)
        if learned_preference:
            return {
                "source": "learned_preference",
                "data": dict(learned_preference),
            }

        for pref in self.mock_db.get("user_preferences", []):
            if str(pref.get("user_id")) == str(user_id) and pref.get("subcategory") == subcategory:
                return {
                    "source": "learned_preference",
                    "data": pref.get("preference_spec")
                }

        # 2순위: 최근 구매 이력 상품 실측 탐색
        for order in self.mock_db.get("orders_and_surveys", []):
            if str(order.get("user_id")) == str(user_id) and order.get("subcategory") == subcategory:
                return {
                    "source": "recent_purchase",
                    "data": order.get("measurement_spec")
                }

        if user_body is not None:
            target_user = parse_user_body(user_body)
        else:
            target_user = next((u for u in self.mock_db.get("users", []) if str(u.get("user_id")) == str(user_id)), None)

        # 3순위 (신발 특화): 유저 등록 shoeSize를 발길이 기준 치수로 반영
        if category_type == "shoes" and target_user and target_user.get("shoe_size"):
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

        # 3순위 (의류): 비슷한 체형 타 사용자의 '맞다' 인증 데이터 탐색
        if (
            target_user
            and target_user.get("height") is not None
            and target_user.get("weight") is not None
        ):
            try:
                t_height = float(target_user["height"])
                t_weight = float(target_user["weight"])
            except (TypeError, ValueError):
                t_height = None
                t_weight = None

            if t_height is not None and t_weight is not None:
                for other in self.mock_db.get("other_users_fits", []):
                    if other.get("subcategory") == subcategory:
                        try:
                            o_height = float(other.get("height", 175.0))
                            o_weight = float(other.get("weight", 70.0))
                        except (TypeError, ValueError):
                            continue

                        if abs(t_height - o_height) <= 3.0 and abs(t_weight - o_weight) <= 4.0:
                            return {
                                "source": "similar_body_profile",
                                "data": other.get("measurement_spec")
                            }

        return {
            "source": "none",
            "data": None
        }

    def update_fit_preferences(self, user_id: str, subcategory: str, fit_type: str, purchased_size_spec: dict):
        """
        [3. Closed-Loop 학습 루프]
        설문에서 "FIT(잘 맞아요)" 응답 시 누적 이동 평균으로 선호 실측 갱신.
        """
        with _MOCK_DB_LOCK:
            prefs = self.mock_db.setdefault("user_preferences", [])
            existing = next((p for p in prefs if p.get("user_id") == user_id and p.get("subcategory") == subcategory), None)

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
                    if category_type == "shoes":
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

CATEGORY_KO_TO_EN: dict[str, str] = {
    "상의": "top",
    "아우터": "outer",
    "하의": "bottom",
    "신발": "shoes",
    "모자": "hat",
    "top": "top",
    "outer": "outer",
    "bottom": "bottom",
    "shoes": "shoes",
    "hat": "hat",
}


def parse_user_body(user_body: dict[str, Any] | None) -> dict[str, float] | None:
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
    if size_resolver is None or not subcategory or not pref_spec:
        return
    mock_db = getattr(size_resolver, "mock_db", None)
    if not isinstance(mock_db, dict):
        return

    with _MOCK_DB_LOCK:
        prefs = mock_db.setdefault("user_preferences", [])
        existing = next(
            (
                p
                for p in prefs
                if str(p.get("user_id")) == str(user_id)
                and p.get("subcategory") == subcategory
            ),
            None,
        )
        if existing is None:
            prefs.append(
                {
                    "preference_id": len(prefs) + 1,
                    "user_id": str(user_id),
                    "subcategory": subcategory,
                    "fit_type": fit_type or "레귤러",
                    "preference_spec": dict(pref_spec),
                    "sample_count": 1,
                }
            )
        else:
            existing["preference_spec"] = dict(pref_spec)
            if fit_type:
                existing["fit_type"] = fit_type


def infer_category_from_measurements(sizes: list[dict[str, Any]]) -> str:
    for entry in sizes:
        if not isinstance(entry, dict):
            continue
        measurements = entry.get("measurements") or {}
        if not isinstance(measurements, dict):
            continue
        keys = set(measurements.keys())
        if keys.intersection({"허리단면", "엉덩이단면", "허벅지단면", "밑위"}):
            return "bottom"
        if keys.intersection({"발길이", "발볼", "발목높이", "굽높이"}):
            return "shoes"
        if keys.intersection({"머리둘레", "챙길이", "깊이"}):
            return "hat"
    return "top"


def extract_payload_metadata(payload: dict[str, Any]) -> dict[str, Any]:
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

    category_type = (
        CATEGORY_KO_TO_EN.get(raw_category)
        or CATEGORY_KO_TO_EN.get(raw_category.lower())
        or infer_category_from_measurements(raw_sizes)
    )

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
    category_type = str(product_data.get("category_type") or "top")

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
