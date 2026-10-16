import json

import pytest

from scripts.audit_color_thumbnail_links import (
    RateLimit,
    check_image,
    extract_evidence,
    full_image_url,
    normalize_color_option_label,
)


def page(tabs, options=None, returned_id=123):
    queries = [
        {"queryKey": ["Detail", 123], "state": {"data": {"data": {
            "goodsNo": returned_id, "goodsNm": "셔츠", "thumbnailImageUrl": "/images/goods_img/123/main.jpg",
            "goodsImages": [{"imageUrl": "/images/prd_img/123/detail.jpg"}],
        }}}},
        {"queryKey": ["Detail", "OtherColorGoods", 123], "state": {"data": {"data": {"curationTabs": tabs}}}},
        {"queryKey": ["Options", 123], "state": {"data": {"data": options or {}}}},
    ]
    payload = {"props": {"pageProps": {"dehydratedState": {"queries": queries}}}}
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(payload) + "</script>"


def test_only_explicit_other_color_tabs_create_links():
    items = [
        {"goodsNo": 123, "displayColorText": "블랙", "imageUrl": "/images/goods_img/123/main.jpg"},
        {"goodsNo": 456, "displayColorText": "화이트", "imageUrl": "/images/goods_img/456/main.jpg"},
    ]
    result = extract_evidence(page([
        {"curationType": "OTHER_COLOR", "curationGoodsList": items},
        {"curationType": "RECOMMENDATION", "curationGoodsList": [{"goodsNo": 789, "displayColorText": "핑크", "imageUrl": "/images/goods_img/789/main.jpg"}]},
    ]), 123)
    assert [row["image_product_id"] for row in result["color_image_links"]] == [123, 456]
    assert [row["scope"] for row in result["color_image_links"]] == ["source_product", "linked_product"]
    assert len(result["product_image_urls"]) == 2


def test_color_swatch_and_unlabelled_images_are_not_product_color_links():
    assert full_image_url("//image.msscdn.net/images/color_image/color/black.png") is None
    result = extract_evidence(page([], {"basic": [
        {"name": "색상", "optionValues": [{"name": "블랙", "imageUrl": "/images/goods_img/123/black.jpg"}]},
        {"name": "사이즈", "optionValues": [{"name": "M", "imageUrl": "/images/goods_img/123/size.jpg"}]},
    ]}), 123)
    assert len(result["option_image_links"]) == 2
    assert len(result["color_image_links"]) == 1
    assert result["color_image_links"][0]["color_raw"] == "블랙"


def test_redirected_product_does_not_get_original_id():
    with pytest.raises(ValueError, match="does not match"):
        extract_evidence(page([], returned_id=456), 123)


def test_combined_color_size_option_preserves_color_and_real_product_id():
    result = extract_evidence(page([], {"basic": [
        {"name": "사이즈", "optionValues": [{"name": "NAVY/OS", "imageUrl": "/images/goods/option-value/123/navy.png"}]},
    ]}), 123)
    link = result["color_image_links"][0]
    assert link["color_raw"] == "NAVY"
    assert link["size_label"] == "OS"
    assert link["image_product_id"] == 123


def test_image_signature_accepts_image_when_cdn_sends_plain_text_mime(monkeypatch):
    class Response:
        status = 200
        headers = {"Content-Type": "text/plain"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _length):
            return b"\xff\xd8\xff" + bytes(61)

    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: Response())
    result = check_image("https://image.msscdn.net/example", RateLimit(0))
    assert result["image_signature"] is True
    assert result["reachable_image"] is True
    assert result["content_type"] == "text/plain"


def test_delivery_annotations_merge_into_one_color_and_prefer_normal_shipping():
    assert normalize_color_option_label("BLACK(10/6 예약발송)") == "BLACK"
    assert normalize_color_option_label("BLACK 일반 발송") == "BLACK"
    result = extract_evidence(page([], {"basic": [{"name": "색상", "optionValues": [
        {"name": "BLACK(10/6 예약발송)", "imageUrl": "/images/goods/option-value/123/reserved.jpg"},
        {"name": "BLACK(일반 발송)", "imageUrl": "/images/goods/option-value/123/normal.jpg"},
    ]}]}), 123)
    assert len(result["color_image_links"]) == 1
    assert result["color_image_links"][0]["color_raw"] == "BLACK"
    assert result["color_image_links"][0]["option_label"] == "BLACK(일반 발송)"
