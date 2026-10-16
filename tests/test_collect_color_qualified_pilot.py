import json
import zipfile

from scripts.collect_color_qualified_pilot import classify, load_products


THUMBNAIL = "https://image.msscdn.net/images/goods_img/123/123_500.jpg"
BLACK_IMAGE = "https://image.msscdn.net/images/goods/option-value/123/black.jpg"
WHITE_IMAGE = "https://image.msscdn.net/images/goods/option-value/123/white.jpg"
SIBLING_IMAGE = "https://image.msscdn.net/images/goods_img/456/456_500.jpg"


def product(name="모자 블랙"):
    return {
        "product_id": 123, "name": name, "name_en": "",
        "gender": {"normalized": "UNISEX"}, "brand": {"id": "brand-a"},
        "dataset": {"logical_category": "모자"},
        "size": {"measurements": [{"size": "M", "measurements": {"둘레": 55.0}}]},
        "options": [{"name": "사이즈", "values": [{"name": "M"}]}],
    }


def source():
    return {"status": "ok", "product_image_urls": [THUMBNAIL],
            "option_data": {"basic": []}, "color_image_links": [],
            "other_color_data": {"curationTabs": []}}


def checks(*urls):
    return {url: {"reachable_image": True} for url in urls}


def test_single_named_color_uses_product_thumbnail():
    result = classify(product(), source(), checks(THUMBNAIL))
    assert result["priority"] == 1
    assert result["mappings"] == [{"product_id": 123, "color_raw": "블랙",
                                   "image_url": THUMBNAIL,
                                   "evidence": "Detail.thumbnailImageUrl+product_name"}]


def test_dropdown_requires_every_distinct_color_image():
    item = product("시그니처 볼캡")
    page = source()
    page["option_data"]["basic"] = [{"name": "색상", "optionValues": [
        {"name": "블랙", "imageUrl": BLACK_IMAGE},
        {"name": "화이트", "imageUrl": WHITE_IMAGE},
    ]}]
    page["color_image_links"] = [
        {"scope": "source_option", "color_raw": color, "image_url": url}
        for color, url in (("블랙", BLACK_IMAGE), ("화이트", WHITE_IMAGE))
    ]
    assert classify(item, page, checks(BLACK_IMAGE, WHITE_IMAGE))["priority"] == 2
    assert classify(item, page, checks(BLACK_IMAGE)) is None


def test_other_url_requires_matching_brand_and_own_image():
    page = source()
    page["color_image_links"] = [{"scope": "source_product", "color_raw": "블랙",
                                  "image_url": THUMBNAIL, "evidence": "OtherColorGoods.OTHER_COLOR"},
                                 {"scope": "linked_product", "color_raw": "화이트",
                                  "image_url": SIBLING_IMAGE}]
    sibling = {"goodsNo": 456, "brand": "brand-a", "displayColorText": "화이트",
               "imageUrl": SIBLING_IMAGE}
    page["other_color_data"]["curationTabs"] = [
        {"curationType": "OTHER_COLOR", "curationGoodsList": [sibling]}]
    assert classify(product(), page, checks(THUMBNAIL, SIBLING_IMAGE))["priority"] == 3
    sibling["brand"] = "other-brand"
    assert classify(product(), page, checks(THUMBNAIL, SIBLING_IMAGE))["priority"] == 4


def test_missing_size_or_image_is_rejected():
    item = product()
    assert classify(item, source(), {}) is None
    item["size"]["measurements"] = []
    assert classify(item, source(), checks(THUMBNAIL)) is None


def test_known_color_image_mismatch_is_rejected():
    item = product()
    item["product_id"] = 4620503
    assert classify(item, source(), checks(THUMBNAIL)) is None


def test_load_products_ignores_dataset_metadata(tmp_path):
    archive_path = tmp_path / "dataset.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("report.json", json.dumps({"total": 1}))
        archive.writestr("image_checks.json", json.dumps({THUMBNAIL: {"reachable_image": True}}))
        archive.writestr("data/hat/123.json", json.dumps(product()))

    assert load_products(archive_path) == [product()]
