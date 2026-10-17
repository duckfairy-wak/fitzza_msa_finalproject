import json

from scripts.expand_color_qualified_dataset import (
    complete_metadata,
    build_pipeline_input,
    load_sources,
    merge_image_checks,
    normalize_embedded_image_urls,
    related_candidates,
)


def test_complete_metadata_matches_dataset_shape():
    product = {
        "product_id": 1,
        "category": {"categoryDepth1Name": "신발"},
        "season": {"original": [], "collection": {"type": "FW"}},
    }
    result = complete_metadata(product)
    assert result["season"]["primary"] == "가을"
    assert result["season"]["primary_candidates"] == ["가을", "겨울"]
    assert result["dataset"] == {
        "logical_category": "신발",
        "primary_season": "가을",
        "gender_scope": "MALE_AND_UNISEX",
    }


def test_related_candidates_exclude_existing_products_and_rank_reviews():
    products = [{"product_id": 1, "dataset": {"logical_category": "모자"}}]
    items = [
        {"goodsNo": 1, "displayColorText": "블랙", "imageUrl": "own", "reviewCount": 999},
        {"goodsNo": 2, "displayColorText": "화이트", "imageUrl": "two", "reviewCount": 10},
        {"goodsNo": 3, "displayColorText": "네이비", "imageUrl": "three", "reviewCount": 50},
    ]
    sources = {1: {"other_color_data": {"curationTabs": [
        {"curationType": "OTHER_COLOR", "curationGoodsList": items}
    ]}}}
    assert related_candidates(products, sources)["모자"] == [3, 2]


def test_transient_image_error_does_not_replace_successful_check():
    checks = {"image": {"status": 200, "reachable_image": True}}

    merge_image_checks(checks, {"image": {"reachable_image": False, "error": "DNS failure"}})

    assert checks["image"] == {"status": 200, "reachable_image": True}


def test_http_image_failure_replaces_successful_check():
    checks = {"image": {"status": 200, "reachable_image": True}}

    merge_image_checks(checks, {"image": {"status": 404, "reachable_image": False}})

    assert checks["image"] == {"status": 404, "reachable_image": False}


def test_load_sources_falls_back_to_expansion_work_cache(tmp_path):
    evidence_dir = tmp_path / "evidence"
    work_dir = tmp_path / "work"
    source_path = work_dir / "sources" / "123.json"
    source_path.parent.mkdir(parents=True)
    source_path.write_text(json.dumps({"option_data": {"basic": []}}), encoding="utf-8")

    sources = load_sources([{"product_id": 123}], evidence_dir, work_dir)

    assert sources[123]["option_image_links"] == []
    assert sources[123]["color_image_links"] == []


def test_embedded_option_image_url_is_normalized():
    product = {"options": [{"values": [{
        "image_url": (
            "https://image.msscdn.net/thumbnails/images/goods/option-value/2837412/"
            "20251230104447_option_69532e8f74da01.40124921."
        )
    }]}]}

    result = normalize_embedded_image_urls(product)

    assert result["options"][0]["values"][0]["image_url"] == (
        "https://image.msscdn.net/images/goods/option-value/2837412/"
        "20251230104447_option_69532e8f74da01.40124921."
    )


def test_pipeline_input_uses_normalized_verified_color_mappings():
    product = {
        "product_id": 2837412,
        "name": "셔츠",
        "category": {"categoryDepth1Name": "상의"},
        "dataset": {"logical_category": "상의"},
        "color_image_mappings": [{
            "color_raw": "BLACK",
            "image_url": (
                "https://image.msscdn.net/thumbnails/images/goods/option-value/2837412/"
                "20251230104447_option_69532e8f74da01.40124921."
            ),
        }],
    }

    result = build_pipeline_input([product])

    assert result["source_product_count"] == 1
    assert result["products_with_colors"] == 1
    assert result["colors"][0]["contexts"][0]["image_url"] == (
        "https://image.msscdn.net/images/goods/option-value/2837412/"
        "20251230104447_option_69532e8f74da01.40124921."
    )
