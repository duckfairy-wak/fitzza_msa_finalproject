"""Size recommendation reads the sizes the data pipeline writes to Qdrant (2026-11-04).

Qdrant payload sizes come from infra/data-pipeline/indexer/vector_points.normalize_sizes:
measurements use the Korean standard fields, and shoes or caps sold without a size chart keep
their labels with empty measurements. Collections loaded before 2026-11-04 use English keys,
which are still read for compatibility.
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.services.size_resolver import (
    SizeCalculator,
    SizeProfileResolver,
    evaluate_single_product_size,
    resolve_product_for_size,
)
from app.services.size_spec_normalizer import (
    MUSINSA_CATEGORY_SPEC_FIELDS,
    QDRANT_MEASUREMENT_KEY_TO_MUSINSA,
    normalize_measurement_spec,
)

VECTOR_POINTS = Path(__file__).resolve().parents[2] / "infra/data-pipeline/indexer/vector_points.py"

QDRANT_TOP_SIZES = [
    {"size": "S", "sequence": 0, "measurements": {"top_length": 68.0, "shoulder": 48.0, "chest": 55.0}},
    {"size": "M", "sequence": 1, "measurements": {"top_length": 70.0, "shoulder": 50.0, "chest": 57.0}},
    {"size": "L", "sequence": 2, "measurements": {"top_length": 72.0, "shoulder": 52.0, "chest": 59.0}},
]
LABEL_ONLY_SHOE_SIZES = [
    {"size": "250", "sequence": 1, "measurements": {}},
    {"size": "260", "sequence": 2, "measurements": {}},
    {"size": "270", "sequence": 3, "measurements": {}},
]
LABEL_ONLY_CAP_SIZES = [
    {"size": "S", "sequence": 1, "measurements": {}},
    {"size": "M", "sequence": 2, "measurements": {}},
]


class BodyClient:
    def __init__(self, body: dict[str, Any]):
        self.body = body

    def get_user_body(self, user_id: int, request_id_header: str | None = None) -> dict[str, Any]:
        return self.body


class MeasurementClient:
    def __init__(self, measurements: dict[int, list[dict[str, Any]]]):
        self.measurements = measurements

    def get_product_measurements(
        self, product_ids: list[int], request_id_header: str | None = None
    ) -> dict[int, list[dict[str, Any]]]:
        return self.measurements


def qdrant_returning(payload: dict[str, Any]) -> MagicMock:
    client = MagicMock()
    client.scroll.return_value = ([SimpleNamespace(payload=payload)], None)
    return client


def empty_resolver() -> SizeProfileResolver:
    return SizeProfileResolver(enable_mock_data=False)


def load_pipeline_vector_points():
    if not VECTOR_POINTS.exists():
        pytest.skip("data pipeline source is not in this checkout")
    spec = importlib.util.spec_from_file_location("pipeline_vector_points", VECTOR_POINTS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pipeline_measurement_fields_match_recommendation_fields() -> None:
    pipeline = load_pipeline_vector_points()
    assert {category: list(fields) for category, fields in pipeline.MEASUREMENT_FIELDS.items()} == (
        MUSINSA_CATEGORY_SPEC_FIELDS
    )


def test_pipeline_payload_sizes_drive_recommendation_without_key_mapping() -> None:
    pipeline = load_pipeline_vector_points()
    rows = [
        {"size": "S", "sequence": 0, "measurements": {"총장": 68, "어깨너비": 48, "가슴단면": 55}},
        {"size": "M", "sequence": 1, "measurements": {"총장": 70, "어깨너비": 50, "가슴단면": 57}},
        {"size": "L", "sequence": 2, "measurements": {"총장": 72, "어깨너비": 52, "가슴단면": 59}},
    ]
    sizes = pipeline.normalize_sizes("상의", rows)
    assert all(not set(size["measurements"]) & set(QDRANT_MEASUREMENT_KEY_TO_MUSINSA) for size in sizes)
    result = SizeCalculator.evaluate(
        [{"product_id": 1, "sizes": sizes}], {"총장": 70.0, "어깨너비": 50.0, "가슴단면": 57.0}, "상의"
    )
    assert result["size_label"] == "M"
    assert result["predicted_fit_score"] == 1.0


def test_legacy_english_keys_are_normalized_to_musinsa_fields() -> None:
    assert normalize_measurement_spec({"top_length": 70, "shoulder": "50", "top_hem": 52}, category="상의") == {
        "총장": 70.0,
        "어깨너비": 50.0,
        "밑단단면": 52.0,
    }
    assert normalize_measurement_spec({"bottom_length": 102, "waist": 40, "bottom_hem": 22}, category="하의") == {
        "총장": 102.0,
        "허리단면": 40.0,
        "밑단단면": 22.0,
    }
    assert normalize_measurement_spec({"foot_length": 26.5}, category="신발") == {"발길이": 265.0}


def test_calculator_picks_closest_size_from_legacy_qdrant_payload() -> None:
    result = SizeCalculator.evaluate(
        [{"product_id": 1, "sizes": QDRANT_TOP_SIZES}],
        {"총장": 72.0, "어깨너비": 52.0, "가슴단면": 59.0},
        "상의",
    )
    assert result["size_label"] == "L"
    assert result["predicted_fit_score"] == 1.0


def test_size_without_comparable_measurements_never_wins() -> None:
    sizes = [{"size": "XS [기모]", "sequence": 0, "measurements": {}}, *QDRANT_TOP_SIZES]
    result = SizeCalculator.evaluate([{"product_id": 1, "sizes": sizes}], {"총장": 70.0, "가슴단면": 57.0}, "상의")
    assert result["size_label"] == "M"

    assert SizeCalculator.evaluate([{"product_id": 1, "sizes": LABEL_ONLY_CAP_SIZES}], {"머리둘레": 58.0}, "모자") is None


def test_label_only_shoe_sizes_match_registered_shoe_size() -> None:
    product = resolve_product_for_size(
        product_id=501,
        qdrant_client=qdrant_returning(
            {"product_id": 501, "product_name": "러닝화", "category": "신발", "subcategory": "스니커즈",
             "sizes": LABEL_ONLY_SHOE_SIZES}
        ),
        collection_name="musinsa_products",
        product_client=MeasurementClient({}),
    )
    assert [size["size"] for size in product["sizes"]] == ["250", "260", "270"]

    result = evaluate_single_product_size(
        size_resolver=empty_resolver(),
        repository=None,
        user_client=BodyClient({"shoeSize": 260}),
        user_id=7,
        product_data=product,
    )
    assert result["recommendedSize"] == "260"
    assert result["fitPercent"] == 100.0


def test_label_only_sizes_are_listed_when_nothing_can_be_compared() -> None:
    repository = MagicMock()
    repository.get_user_size_preference.return_value = {"머리둘레": 58.0}
    result = evaluate_single_product_size(
        size_resolver=empty_resolver(),
        repository=repository,
        user_client=BodyClient({}),
        user_id=7,
        product_data={"product_id": 502, "category_type": "모자", "subcategory": "캡/야구모자",
                      "fit_type": "레귤러", "sizes": LABEL_ONLY_CAP_SIZES},
    )
    assert result == {
        "recommendedSize": None,
        "fitPercent": None,
        "evidence": "실측표가 없는 상품이라 맞춤 추천 대신 판매 사이즈를 안내합니다: S, M",
    }


def test_label_only_sizes_are_listed_without_body_info_except_for_shoes() -> None:
    cap = evaluate_single_product_size(
        size_resolver=empty_resolver(),
        repository=None,
        user_client=BodyClient({}),
        user_id=7,
        product_data={"product_id": 502, "category_type": "모자", "subcategory": "캡/야구모자",
                      "fit_type": "레귤러", "sizes": LABEL_ONLY_CAP_SIZES},
    )
    assert cap["evidence"] == "실측표가 없는 상품이라 맞춤 추천 대신 판매 사이즈를 안내합니다: S, M"

    # 신발은 신발 사이즈를 등록하면 라벨로 추천할 수 있으므로 등록 안내를 유지한다.
    shoe = evaluate_single_product_size(
        size_resolver=empty_resolver(),
        repository=None,
        user_client=BodyClient({}),
        user_id=7,
        product_data={"product_id": 501, "category_type": "신발", "subcategory": "스니커즈",
                      "fit_type": "레귤러", "sizes": LABEL_ONLY_SHOE_SIZES},
    )
    assert shoe == {
        "recommendedSize": None,
        "fitPercent": None,
        "evidence": "체형 정보를 등록하시면 맞춤 사이즈를 추천해 드립니다.",
    }


def test_product_service_measurements_fill_qdrant_labels_without_dropping_them() -> None:
    qdrant = qdrant_returning(
        {"product_id": 503, "category": "모자", "subcategory": "캡/야구모자", "sizes": LABEL_ONLY_CAP_SIZES}
    )
    measured = resolve_product_for_size(
        product_id=503,
        qdrant_client=qdrant,
        collection_name="musinsa_products",
        product_client=MeasurementClient({503: [{"size": "M", "measurements": {"머리둘레": 58.0}},
                                                {"size": "L", "measurements": {"머리둘레": 60.0}}]}),
    )
    assert measured["sizes"] == [
        {"size": "S", "sequence": 1, "measurements": {}},
        {"size": "M", "sequence": 2, "measurements": {"머리둘레": 58.0}},
        {"size": "L", "measurements": {"머리둘레": 60.0}},
    ]

    without_qdrant_sizes = resolve_product_for_size(
        product_id=503,
        qdrant_client=qdrant_returning({"product_id": 503, "category": "모자", "sizes": []}),
        collection_name="musinsa_products",
        product_client=MeasurementClient({503: [{"size": "M", "measurements": {"머리둘레": 58.0}}]}),
    )
    assert without_qdrant_sizes["sizes"] == [{"size": "M", "measurements": {"머리둘레": 58.0}}]

    labels_only = resolve_product_for_size(
        product_id=503,
        qdrant_client=qdrant,
        collection_name="musinsa_products",
        product_client=MeasurementClient({}),
    )
    assert labels_only["sizes"] == LABEL_ONLY_CAP_SIZES
