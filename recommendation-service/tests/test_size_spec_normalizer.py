import pytest

from app.services.size_spec_normalizer import (
    MUSINSA_CATEGORY_SPEC_FIELDS,
    get_musinsa_spec_fields,
    parse_numeric_measurement,
    normalize_measurement_spec,
    MusinsaSizeSpecResolver,
)
from app.services.size_resolver import SizeCalculator


class TestMusinsaCategorySpecFields:
    def test_category_spec_fields_exact_match(self):
        """무신사 5대 표준 한글 카테고리별 실측 필드가 정확히 정의되어 있는지 확인"""
        assert MUSINSA_CATEGORY_SPEC_FIELDS["상의"] == [
            "총장", "어깨너비", "가슴단면", "소매길이", "밑단단면", "소매부리단면", "암홀"
        ]
        assert MUSINSA_CATEGORY_SPEC_FIELDS["아우터"] == [
            "총장", "어깨너비", "가슴단면", "소매길이", "밑단단면", "소매부리단면", "암홀"
        ]
        assert MUSINSA_CATEGORY_SPEC_FIELDS["하의"] == [
            "총장", "허리단면", "엉덩이단면", "허벅지단면", "밑위", "밑단단면"
        ]
        assert MUSINSA_CATEGORY_SPEC_FIELDS["신발"] == [
            "발길이", "발볼", "발목높이", "굽높이"
        ]
        assert MUSINSA_CATEGORY_SPEC_FIELDS["모자"] == [
            "머리둘레", "챙길이", "깊이"
        ]

    def test_get_musinsa_spec_fields(self):
        """한글 및 영문 레거시 카테고리에 대한 실측 필드 목록 조회를 검증한다."""
        # 한글 카테고리 직접 조회
        assert get_musinsa_spec_fields("상의") == MUSINSA_CATEGORY_SPEC_FIELDS["상의"]
        assert get_musinsa_spec_fields("아우터") == MUSINSA_CATEGORY_SPEC_FIELDS["아우터"]
        assert get_musinsa_spec_fields("하의") == MUSINSA_CATEGORY_SPEC_FIELDS["하의"]
        assert get_musinsa_spec_fields("신발") == MUSINSA_CATEGORY_SPEC_FIELDS["신발"]
        assert get_musinsa_spec_fields("모자") == MUSINSA_CATEGORY_SPEC_FIELDS["모자"]
        # 영문 레거시 호환성 지원
        assert get_musinsa_spec_fields("top") == MUSINSA_CATEGORY_SPEC_FIELDS["상의"]
        assert get_musinsa_spec_fields("TOP") == MUSINSA_CATEGORY_SPEC_FIELDS["상의"]
        assert get_musinsa_spec_fields("bottom") == MUSINSA_CATEGORY_SPEC_FIELDS["하의"]
        assert get_musinsa_spec_fields("shoes") == MUSINSA_CATEGORY_SPEC_FIELDS["신발"]
        assert get_musinsa_spec_fields("hat") == MUSINSA_CATEGORY_SPEC_FIELDS["모자"]
        assert get_musinsa_spec_fields("unknown") == []


class TestParseNumericMeasurement:
    def test_numeric_float_and_int(self):
        """정수, 실수, 숫자 문자열의 실측값 파싱을 검증한다."""
        assert parse_numeric_measurement(72) == 72.0
        assert parse_numeric_measurement(72.5) == 72.5
        assert parse_numeric_measurement("72.5") == 72.5

    def test_numeric_with_units(self):
        """단위(cm, mm)가 포함된 문자열의 실측값 파싱을 검증한다."""
        assert parse_numeric_measurement("72.5cm") == 72.5
        assert parse_numeric_measurement(" 102 cm ") == 102.0
        assert parse_numeric_measurement("260mm") == 260.0

    def test_shoes_cm_to_mm_conversion(self):
        """신발 카테고리에서 cm 단위 입력을 mm 단위로 자동 변환하는지 검증한다."""
        # 신발에서 20~35cm로 들어온 경우 mm 단위(* 10)로 자동 변환
        assert parse_numeric_measurement(26.5, is_shoes=True) == 265.0
        assert parse_numeric_measurement("27.0cm", is_shoes=True) == 270.0
        assert parse_numeric_measurement("260", is_shoes=True) == 260.0

    def test_invalid_values(self):
        """유효하지 않은 입력(None, 0 이하, 비숫자 문자열)이 None으로 처리되는지 검증한다."""
        assert parse_numeric_measurement(None) is None
        assert parse_numeric_measurement(0) is None
        assert parse_numeric_measurement(-10) is None
        assert parse_numeric_measurement("invalid") is None


class TestNormalizeMeasurementSpec:
    def test_normalize_top_spec(self):
        """상의 실측 딕셔너리 정규화 및 비표준 필드 제거를 검증한다."""
        raw = {
            "총장": 72.0,
            "어깨너비": "53cm",
            "가슴단면": 61,
            "소매길이": 62.0,
            "암홀": 26.0,
            "소매부리단면": 11.5,
            "밑단단면": 58.0,
            "기타비표준필드": 999.0,
        }
        normalized = normalize_measurement_spec(raw, category="top")
        assert normalized == {
            "총장": 72.0,
            "어깨너비": 53.0,
            "가슴단면": 61.0,
            "소매길이": 62.0,
            "암홀": 26.0,
            "소매부리단면": 11.5,
            "밑단단면": 58.0,
        }
        assert "기타비표준필드" not in normalized

    def test_normalize_bottom_spec(self):
        """하의 실측 딕셔너리 정규화를 검증한다."""
        raw = {
            "총장": "102",
            "허리단면": 41.0,
            "엉덩이단면": 52.0,
            "허벅지단면": 31.0,
            "밑위": 29.0,
            "밑단단면": 21.0,
        }
        normalized = normalize_measurement_spec(raw, category="bottom")
        assert normalized["총장"] == 102.0
        assert normalized["허리단면"] == 41.0
        assert normalized["밑위"] == 29.0

    def test_normalize_shoes_spec(self):
        """신발 실측 딕셔너리 정규화 및 발길이 단위 변환을 검증한다."""
        raw = {
            "발길이": 26.5,  # 신발 cm -> mm 변환 확인
            "발볼": "10.0cm",
            "발목높이": 8.0,
            "굽높이": 3.5,
        }
        normalized = normalize_measurement_spec(raw, category="shoes")
        assert normalized["발길이"] == 265.0
        assert normalized["굽높이"] == 3.5

    def test_normalize_hat_spec(self):
        """모자 실측 딕셔너리 정규화를 검증한다."""
        raw = {
            "머리둘레": 58.0,
            "챙길이": 7.5,
            "깊이": 16.0,
        }
        normalized = normalize_measurement_spec(raw, category="hat")
        assert normalized["머리둘레"] == 58.0
        assert normalized["챙길이"] == 7.5
        assert normalized["깊이"] == 16.0


class TestMusinsaSizeSpecResolverClass:
    def test_resolver_facade(self):
        """MusinsaSizeSpecResolver 파사드 클래스의 카테고리 및 정규화 메서드를 검증한다."""
        categories = MusinsaSizeSpecResolver.get_supported_categories()
        assert "상의" in categories
        assert "아우터" in categories
        assert "하의" in categories
        assert "신발" in categories
        assert "모자" in categories

        fields = MusinsaSizeSpecResolver.get_spec_fields("상의")
        assert "총장" in fields

        norm = MusinsaSizeSpecResolver.normalize({"총장": "70"}, category="상의")
        assert norm == {"총장": 70.0}


class TestSizeCalculatorWithMusinsaSpecs:
    def test_size_calculator_evaluation(self):
        """SizeCalculator가 기준 실측과 가장 가까운 사이즈를 추천하는지 검증한다."""
        candidate_products = [
            {
                "product_id": 101,
                "product_name": "베이직 니트",
                "sizes": [
                    {
                        "size": "M",
                        "measurements": {"총장": 68.0, "어깨너비": 50.0, "가슴단면": 56.0, "소매길이": 59.0}
                    },
                    {
                        "size": "L",
                        "measurements": {"총장": 72.0, "어깨너비": 53.0, "가슴단면": 60.0, "소매길이": 62.0}
                    }
                ]
            }
        ]
        baseline = {"총장": 71.5, "어깨너비": 52.5, "가슴단면": 60.5, "소매길이": 61.5}

        best = SizeCalculator.evaluate(
            candidate_products=candidate_products,
            baseline_spec=baseline,
            category_type="top"
        )
        assert best is not None
        assert best["product_id"] == 101
        assert best["size_label"] == "L"
        assert best["predicted_fit_score"] > 0.8

    def test_shoes_label_matching_exact(self):
        """실측표 없이 라벨(250, 260, 270)만 있는 신발 상품의 표기 사이즈 직접 매칭 테스트"""
        candidate_shoes = [
            {
                "product_id": 201,
                "product_name": "클래식 스니커즈",
                "sizes": [
                    {"size": "250", "measurements": {}},
                    {"size": "260", "measurements": {}},
                    {"size": "270", "measurements": {}},
                ]
            }
        ]
        user_baseline = {"shoe_size": 260.0}

        best = SizeCalculator.evaluate(
            candidate_products=candidate_shoes,
            baseline_spec=user_baseline,
            category_type="shoes"
        )
        assert best is not None
        assert best["product_id"] == 201
        assert best["size_label"] == "260"
        assert best["predicted_fit_score"] == 1.0

    def test_shoes_label_matching_half_size_tolerance(self):
        """5mm(한 사이즈) 차이 옵션은 발길이 허용치 기준 50%로 감점되는지 테스트"""
        candidate_shoes = [
            {
                "product_id": 202,
                "product_name": "러닝화",
                "sizes": [
                    {"size": "255", "measurements": {}},
                    {"size": "275", "measurements": {}},
                ]
            }
        ]
        user_baseline = {"shoe_size": 260.0}

        best = SizeCalculator.evaluate(
            candidate_products=candidate_shoes,
            baseline_spec=user_baseline,
            category_type="shoes"
        )
        assert best is not None
        assert best["size_label"] == "255"
        assert best["predicted_fit_score"] == 0.5

    def test_shoes_with_detailed_measurements(self):
        """정밀 실측표가 있는 신발의 경우 실측 기반 채점 테스트"""
        candidate_shoes = [
            {
                "product_id": 203,
                "product_name": "수제화 더비슈즈",
                "sizes": [
                    {
                        "size": "260",
                        "measurements": {"발길이": 275.0, "발볼": 97.0, "굽높이": 4.0}
                    },
                    {
                        "size": "270",
                        "measurements": {"발길이": 285.0, "발볼": 102.0, "굽높이": 4.0}
                    }
                ]
            }
        ]
        user_baseline = {"발길이": 274.0, "발볼": 96.5, "굽높이": 4.0}

        best = SizeCalculator.evaluate(
            candidate_products=candidate_shoes,
            baseline_spec=user_baseline,
            category_type="shoes"
        )
        assert best is not None
        assert best["size_label"] == "260"
        assert best["predicted_fit_score"] > 0.9


class TestWeightedFitScore:
    def test_outer_weighted_average_matches_agreed_example(self):
        """아우터에서 가슴 +3, 어깨 +2, 총장 +5, 소매 +3 차이는 가중 평균 53%가 되어야 한다."""
        product = {
            "product_id": 301,
            "sizes": [
                {"size": "L", "measurements": {"가슴단면": 63.0, "어깨너비": 52.0, "총장": 105.0, "소매길이": 66.0}},
            ],
        }
        baseline = {"가슴단면": 60.0, "어깨너비": 50.0, "총장": 100.0, "소매길이": 63.0}

        best = SizeCalculator.evaluate([product], baseline, "아우터")

        assert best is not None
        assert best["size_label"] == "L"
        assert best["predicted_fit_score"] == 0.53

    def test_many_measured_fields_do_not_collapse_score_to_zero(self):
        """항목이 많아도 합계 오차로 0%가 되지 않고 항목별 점수 평균을 유지해야 한다."""
        product = {
            "product_id": 302,
            "sizes": [
                {
                    "size": "XL",
                    "measurements": {
                        "가슴단면": 61.0, "어깨너비": 51.0, "총장": 74.0, "소매길이": 64.0,
                        "암홀": 26.0, "밑단단면": 57.0, "소매부리단면": 13.0,
                    },
                },
            ],
        }
        baseline = {
            "가슴단면": 60.0, "어깨너비": 50.0, "총장": 70.0, "소매길이": 61.0,
            "암홀": 25.0, "밑단단면": 54.0, "소매부리단면": 12.0,
        }

        best = SizeCalculator.evaluate([product], baseline, "상의")

        assert best is not None
        assert best["predicted_fit_score"] > 0.5

    def test_primary_field_zero_caps_score(self):
        """가중치가 가장 큰 가슴단면이 0점이면 다른 항목이 맞아도 적합도는 30% 이하로 제한된다."""
        product = {
            "product_id": 303,
            "sizes": [
                {"size": "M", "measurements": {"가슴단면": 52.0, "어깨너비": 50.0, "총장": 70.0, "소매길이": 61.0}},
            ],
        }
        baseline = {"가슴단면": 60.0, "어깨너비": 50.0, "총장": 70.0, "소매길이": 61.0}

        best = SizeCalculator.evaluate([product], baseline, "상의")

        assert best is not None
        assert best["predicted_fit_score"] == 0.3

    def test_size_position_reports_largest_size_when_all_sizes_are_small(self):
        """모든 사이즈의 핵심 항목이 기준보다 작으면 가장 큰 사이즈를 경계 사이즈로 알려야 한다."""
        product = {
            "product_id": 304,
            "sizes": [
                {"size": "XL", "measurements": {"가슴단면": 58.0, "어깨너비": 50.0}},
                {"size": "XXL", "measurements": {"가슴단면": 61.0, "어깨너비": 52.0}},
            ],
        }
        baseline = {"가슴단면": 66.0, "어깨너비": 56.0}

        best = SizeCalculator.evaluate([product], baseline, "아우터")

        assert best is not None
        assert best["size_label"] == "XXL"
        assert best["size_position"] == "too_small"
        assert best["boundary_size_label"] == "XXL"
        assert best["field_diffs"] == {"가슴단면": -5.0, "어깨너비": -4.0}

    def test_size_position_in_range_when_core_diffs_have_mixed_signs(self):
        """핵심 항목 차이 부호가 섞이면 사이즈 범위 안의 핏 차이로 판정한다."""
        product = {
            "product_id": 305,
            "sizes": [
                {"size": "M", "measurements": {"가슴단면": 55.0, "어깨너비": 52.0}},
                {"size": "L", "measurements": {"가슴단면": 58.0, "어깨너비": 54.0}},
            ],
        }
        baseline = {"가슴단면": 60.0, "어깨너비": 50.0}

        best = SizeCalculator.evaluate([product], baseline, "상의")

        assert best is not None
        assert best["size_position"] == "in_range"
        assert best["boundary_size_label"] is None


class TestTieredFitEvidence:
    def test_good_fit_keeps_source_evidence(self):
        from app.services.size_resolver import build_fit_evidence

        text = build_fit_evidence("learned_preference", "L", 85.0, {"field_diffs": {"어깨너비": 2.0}}, "상의")
        assert text == "기존 구매·설문 기반 선호 실측과 가장 유사한 사이즈입니다."

    def test_fair_fit_appends_worst_core_field(self):
        from app.services.size_resolver import build_fit_evidence

        rec = {"field_diffs": {"가슴단면": 1.0, "어깨너비": 2.0, "총장": 5.0}}
        text = build_fit_evidence("learned_preference", "L", 62.0, rec, "아우터")
        assert text == (
            "기존 구매·설문 기반 선호 실측과 가장 유사한 사이즈입니다. "
            "다만 어깨가 평소 입으시는 실측보다 2cm 넓어요."
        )

    def test_low_fit_reports_largest_size_is_small(self):
        from app.services.size_resolver import build_fit_evidence

        rec = {"size_position": "too_small", "boundary_size_label": "XXL"}
        text = build_fit_evidence("learned_preference", "XXL", 25.0, rec, "아우터")
        assert text == "가장 큰 사이즈인 XXL도 평소 입으시는 실측보다 작을 수 있어요. 구매 전 실측표를 확인해 주세요."

    def test_low_fit_reports_smallest_size_is_large_with_source_basis(self):
        from app.services.size_resolver import build_fit_evidence

        rec = {"size_position": "too_large", "boundary_size_label": "S"}
        text = build_fit_evidence("similar_body_profile", "S", 20.0, rec, "상의")
        assert text == "가장 작은 사이즈인 S도 비슷한 체형 고객의 실측보다 클 수 있어요. 구매 전 실측표를 확인해 주세요."

    def test_low_fit_in_range_reports_closest_size(self):
        from app.services.size_resolver import build_fit_evidence

        rec = {"size_position": "in_range", "boundary_size_label": None}
        assert build_fit_evidence("learned_preference", "L", 31.0, rec, "상의") == (
            "평소 입으시는 실측과 핏 차이가 커요. 가장 가까운 사이즈는 L이에요."
        )
        assert build_fit_evidence("body_profile", "XS", 31.0, rec, "상의") == (
            "등록하신 사이즈와 핏 차이가 커요. 가장 가까운 사이즈는 XS예요."
        )

    def test_thresholds_follow_settings(self, monkeypatch):
        from app.services.size_resolver import build_fit_evidence

        monkeypatch.setenv("SIZE_FIT_GOOD_THRESHOLD", "50")
        rec = {"field_diffs": {"어깨너비": 2.0}}
        assert build_fit_evidence("learned_preference", "L", 62.0, rec, "상의") == (
            "기존 구매·설문 기반 선호 실측과 가장 유사한 사이즈입니다."
        )
