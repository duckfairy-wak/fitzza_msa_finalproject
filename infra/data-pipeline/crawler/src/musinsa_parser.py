from __future__ import annotations

import json
from typing import Any

from bs4 import BeautifulSoup

from src.color_image_mappings import (
    extract_color_image_mappings,
    extract_accessory_image_fallback,
)


FIT_TYPE_BY_RAW = {
    "레귤러": "REGULAR",
    "루즈": "RELAXED",
    "오버 사이즈": "OVERSIZED",
    "오버사이즈": "OVERSIZED",
    "슬림": "SLIM",
    "크롭": "CROPPED",
}

FIT_TEXT_PATTERNS = (
    ("오버핏", "OVERSIZED"),
    ("오버 사이즈", "OVERSIZED"),
    ("루즈핏", "RELAXED"),
    ("루즈 핏", "RELAXED"),
    ("레귤러핏", "REGULAR"),
    ("레귤러 핏", "REGULAR"),
    ("슬림핏", "SLIM"),
    ("슬림 핏", "SLIM"),
    ("크롭핏", "CROPPED"),
    ("크롭 핏", "CROPPED"),
)


def _full_image_url(url: str | None) -> str | None:
    if not url:
        return url
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("/"):
        return f"https://image.msscdn.net{url}"
    return url


def _query_data(next_data: dict[str, Any], prefix: list[Any]) -> Any | None:
    queries = (
        next_data.get("props", {})
        .get("pageProps", {})
        .get("dehydratedState", {})
        .get("queries", [])
    )

    for query in queries:
        key = query.get("queryKey", [])
        if key[: len(prefix)] != prefix:
            continue

        data = query.get("state", {}).get("data")
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data

    return None


def _normalize_gender(raw_sex: list[str] | None) -> dict[str, Any]:
    values = list(dict.fromkeys(raw_sex or []))
    normalized = "UNKNOWN"

    has_male = "남성" in values
    has_female = "여성" in values
    has_unisex = "공용" in values

    if has_unisex or (has_male and has_female):
        normalized = "UNISEX"
    elif has_male:
        normalized = "MALE"
    elif has_female:
        normalized = "FEMALE_ONLY"

    return {
        "raw": values,
        "normalized": normalized,
    }


def _normalize_collection(
    season_year: Any,
    season_code: Any,
    original_seasons: list[str],
) -> dict[str, Any]:
    """
    무신사 상세 데이터의 season 값이 있으면 그것을 우선 사용한다.
    현재 관찰된 값:
      1 -> SS
      2 -> FW

    공식 시즌 값이 없을 때만 계절 태그로 보조 추론한다.
    """
    code = str(season_code) if season_code not in (None, "") else None
    official_map = {
        "1": "SS",
        "2": "FW",
        "SS": "SS",
        "S/S": "SS",
        "FW": "FW",
        "F/W": "FW",
    }

    collection = official_map.get(code) if code else None
    source = "official" if collection else None

    if collection is None and original_seasons:
        season_set = set(original_seasons)
        ss = {"봄", "여름"}
        fw = {"가을", "겨울"}

        if season_set and season_set.issubset(ss):
            collection = "SS"
            source = "inferred_from_season_tags"
        elif season_set and season_set.issubset(fw):
            collection = "FW"
            source = "inferred_from_season_tags"

    try:
        year = int(season_year) if season_year not in (None, "") else None
    except (TypeError, ValueError):
        year = None

    if year is not None and year <= 0:
        year = None

    return {
        "type": collection,
        "year": year,
        "raw_code": code,
        "source": source,
    }


def _first_feature(features: dict[str, list[str]], names: set[str]) -> str | None:
    for key, values in features.items():
        if key.strip() in names and values:
            return values[0].strip() or None
    return None


def _normalize_fit(
    features: dict[str, list[str]], goods_contents: object
) -> tuple[str | None, dict[str, str] | None]:
    raw_fit = _first_feature(features, {"핏"})
    if raw_fit:
        normalized = FIT_TYPE_BY_RAW.get(raw_fit)
        return normalized, {
            "raw": raw_fit,
            "source": "goodsMaterial",
        }

    if not isinstance(goods_contents, str):
        return None, None
    text = BeautifulSoup(goods_contents, "html.parser").get_text(" ", strip=True)
    for phrase, normalized in FIT_TEXT_PATTERNS:
        if phrase in text:
            return normalized, {
                "raw": phrase,
                "source": "goodsContents_explicit_text",
            }
    return None, None


def normalize_musinsa_product(html: str, source_url: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    next_script = soup.find("script", id="__NEXT_DATA__")

    if not next_script or not next_script.string:
        raise ValueError("__NEXT_DATA__를 찾지 못했습니다.")

    next_data = json.loads(next_script.string)
    queries = (
        next_data.get("props", {})
        .get("pageProps", {})
        .get("dehydratedState", {})
        .get("queries", [])
    )

    product_id = None
    for query in queries:
        key = query.get("queryKey", [])
        if len(key) == 2 and key[0] == "Detail" and isinstance(key[1], int):
            product_id = key[1]
            break

    if product_id is None:
        raise ValueError("상품 번호를 찾지 못했습니다.")

    detail = _query_data(next_data, ["Detail", product_id]) or {}
    options = _query_data(next_data, ["Options", product_id]) or {}
    if type(detail.get("goodsNo")) is not int or detail["goodsNo"] != product_id:
        raise ValueError("Detail product identity mismatch")

    brand_info = detail.get("brandInfo") or {}
    price = detail.get("goodsPrice") or {}
    review = detail.get("goodsReview") or {}

    features: dict[str, list[str]] = {}
    for group in (detail.get("goodsMaterial") or {}).get("materials", []):
        selected = [
            item.get("name", "").replace("|", " ")
            for item in group.get("items", [])
            if item.get("isSelected")
        ]
        if selected:
            features[group.get("name", "")] = selected

    original_seasons = features.get("계절", [])
    material = _first_feature(features, {"소재", "재질", "주요 소재"})
    fit_type, fit_evidence = _normalize_fit(features, detail.get("goodsContents"))

    option_groups = []
    for group in options.get("basic", []):
        option_groups.append(
            {
                "name": group.get("name"),
                "display_type": group.get("displayType"),
                "values": [
                    {
                        "name": value.get("name"),
                        "code": value.get("code"),
                        "image_url": _full_image_url(value.get("imageUrl")),
                        "color": value.get("color"),
                    }
                    for value in group.get("optionValues", [])
                ],
            }
        )

    option_items = []
    for item in options.get("optionItems", []):
        option_items.append(
            {
                "id": item.get("no"),
                "managed_code": item.get("managedCode"),
                "price_delta": item.get("price"),
                "activated": item.get("activated"),
                "values": [
                    value.get("name") for value in item.get("optionValues", [])
                ],
            }
        )

    images = [_full_image_url(detail.get("thumbnailImageUrl"))]
    images.extend(
        _full_image_url(image.get("imageUrl"))
        for image in detail.get("goodsImages", [])
    )
    images = [image for image in images if image]
    color_image_mappings = extract_color_image_mappings(product_id, options)
    category = detail.get("category") or {}
    if (not color_image_mappings
            and category.get("categoryDepth1Name") in {"신발", "모자"}):
        color_image_mappings = extract_accessory_image_fallback(
            product_id,
            options,
            images,
        )

    return {
        "source": "musinsa",
        "source_url": source_url,
        "product_id": product_id,
        "name": detail.get("goodsNm"),
        "name_en": detail.get("goodsNmEng"),
        "style_no": detail.get("styleNo"),

        "gender": _normalize_gender(detail.get("sex")),

        "brand": {
            "id": detail.get("brand"),
            "name": brand_info.get("brandName"),
            "name_en": brand_info.get("brandEnglishName"),
        },

        "category": category,

        "season": {
            "original": original_seasons,
            "primary": None,
            "collection": _normalize_collection(
                detail.get("seasonYear"),
                detail.get("season"),
                original_seasons,
            ),
        },

        "price": {
            "normal": price.get("normalPrice"),
            "sale": price.get("salePrice"),
            "discount_rate": price.get("discountRate"),
            "currency": price.get("currency"),
        },

        "images": images,
        "features": features,
        "material": material,
        "fit_type": fit_type,
        "attribute_evidence": {
            "material": (
                {"raw": material, "source": "goodsMaterial"}
                if material is not None
                else None
            ),
            "fit": fit_evidence,
        },

        # actual-size API 병합 전 기본값.
        # V4 crawler가 이후 실제 실측 데이터로 교체한다.
        "size": {
            "available": bool(detail.get("isUseSize")),
            "type_name": None,
            "type_number": detail.get("sizeType"),
            "unit": "cm",
            "description": None,
            "guide_image": None,
            "measurements": [],
        },

        "options": option_groups,
        "option_items": option_items,
        "color_image_mappings": color_image_mappings,

        "review": {
            "rating": review.get("satisfactionScore"),
            "count": review.get("totalCount"),
        },
    }
