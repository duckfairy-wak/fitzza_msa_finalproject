from scripts.build_color_size_dataset import project_product


def product() -> dict:
    return {
        "product_id": 1033853,
        "name": "셔츠 [2color]",
        "name_en": "",
        "dataset": {"logical_category": "상의"},
        "images": ["https://example.com/product.jpg"],
        "options": [{"name": "컬러", "values": [{"name": "BLACK"}, {"name": "NAVY"}]}],
        "option_items": [],
        "size": {
            "measurements": [
                {"size": "M", "sequence": 0, "measurements": {"총장": 73.0}},
                {"size": "L", "sequence": 1, "measurements": {"총장": 75.0}},
            ]
        },
    }


def test_product_size_chart_crosses_all_colors_without_stock() -> None:
    source = product()
    projected, audit = project_product(source)

    assert audit["combination_count"] == 4
    assert audit["unlinked_count"] == 0
    assert {variant["color"]["name"] for variant in projected["variants"]} == {"black", "navy"}
    assert all({option["size"] for option in variant["options"]} == {"M", "L"} for variant in projected["variants"])
    assert all(option["relation_source"] == "product_size_chart" for variant in projected["variants"] for option in variant["options"])
    assert projected["images"] == source["images"]
    assert source["size"]["measurements"][0].get("id") is None


def test_color_specific_rows_choose_matching_measurements() -> None:
    source = product()
    source["size"]["measurements"] = [
        {"size": "BLACK - M", "measurements": {"총장": 73.0}},
        {"size": "NAVY - M", "measurements": {"총장": 74.0}},
    ]
    projected, audit = project_product(source)

    assert audit["combination_count"] == 2
    assert audit["unlinked_count"] == 0
    rows = {row["id"]: row for row in projected["size"]["measurements"]}
    values = {
        variant["color"]["name"]: rows[variant["options"][0]["measurement_id"]]["values"]["총장"]
        for variant in projected["variants"]
    }
    assert values == {"black": 73.0, "navy": 74.0}


def test_missing_color_does_not_create_fake_variant() -> None:
    source = product()
    source["options"] = [{"name": "사이즈", "values": [{"name": "M"}]}]
    source["name"] = "기본 셔츠"
    projected, audit = project_product(source)

    assert projected["variants"] == []
    assert audit["color_source"] == "unresolved"
