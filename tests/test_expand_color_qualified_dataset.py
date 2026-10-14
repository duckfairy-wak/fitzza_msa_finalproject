from scripts.expand_color_qualified_dataset import complete_metadata, related_candidates


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
