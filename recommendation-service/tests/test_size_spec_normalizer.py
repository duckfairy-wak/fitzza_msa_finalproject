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
        assert parse_numeric_measurement(72) == 72.0
        assert parse_numeric_measurement(72.5) == 72.5
        assert parse_numeric_measurement("72.5") == 72.5

    def test_numeric_with_units(self):
        assert parse_numeric_measurement("72.5cm") == 72.5
        assert parse_numeric_measurement(" 102 cm ") == 102.0
        assert parse_numeric_measurement("260mm") == 260.0

    def test_shoes_cm_to_mm_conversion(self):
        # 신발에서 20~35cm로 들어온 경우 mm 단위(* 10)로 자동 변환
        assert parse_numeric_measurement(26.5, is_shoes=True) == 265.0
        assert parse_numeric_measurement("27.0cm", is_shoes=True) == 270.0
        assert parse_numeric_measurement("260", is_shoes=True) == 260.0

    def test_invalid_values(self):
        assert parse_numeric_measurement(None) is None
        assert parse_numeric_measurement(0) is None
        assert parse_numeric_measurement(-10) is None
        assert parse_numeric_measurement("invalid") is None


class TestNormalizeMeasurementSpec:
    def test_normalize_top_spec(self):
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
        """5mm 차이 옵션(반업/반다운)에 대한 점수 감점(85%) 테스트"""
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
        assert best["predicted_fit_score"] == 0.85

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
