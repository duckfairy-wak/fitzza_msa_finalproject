"""Extract explicit product/option images; never infer color from product names."""

from collections import defaultdict
from urllib.parse import urlparse

IMAGE_HOSTS = {"image.msscdn.net", "image.musinsa.com", "image.musinsa.co.kr"}


def product_image_url(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    url = value.strip()
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = "https://image.msscdn.net" + url
    try:
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname not in IMAGE_HOSTS
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            return None
    except ValueError:
        return None
    if "/color_image/" in parsed.path.lower() or "/colorchip/" in parsed.path.lower():
        return None
    return url


def extract_color_image_mappings(product_id: int, options: dict) -> list[dict]:
    groups = [group for group in options.get("basic", [])
              if group.get("displayType") == "COLOR_CHIP" and not group.get("isDeleted")]
    # Two independently selectable color dimensions need an explicit combination mapping.
    if len(groups) != 1:
        return []
    group = groups[0]
    if type(group.get("no")) is not int:
        return []
    linked_values = set()
    for item in options.get("optionItems", []):
        if (type(item.get("goodsNo")) is not int or item["goodsNo"] != product_id
                or item.get("activated") is not True or item.get("isDeleted")):
            continue
        for value in item.get("optionValues", []):
            if (value.get("optionNo") == group["no"] and type(value.get("no")) is int
                    and value["no"] in (item.get("optionValueNos") or [])):
                linked_values.add(value["no"])
    candidates = []
    images_to_colors = defaultdict(set)
    seen = set()
    for value in group.get("optionValues", []):
        if (type(value.get("no")) is not int or value["no"] not in linked_values
                or value.get("optionNo") != group["no"] or value.get("isDeleted")):
            continue
        raw = value.get("name")
        image = product_image_url(value.get("imageUrl"))
        if not isinstance(raw, str) or not raw.strip() or not image:
            continue
        pair = (raw.strip().lower(), image)
        if pair in seen:
            continue
        seen.add(pair)
        images_to_colors[image].add(pair[0])
        candidates.append({"product_id": product_id, "color_raw": raw.strip(), "image_url": image,
            "evidence": "Options.basic.COLOR_CHIP.imageUrl",
            "source_option_group_id": group["no"], "source_option_value_id": value["no"]})
    # A shared placeholder cannot prove two different colors' image relationships.
    return [item for item in candidates if len(images_to_colors[item["image_url"]]) == 1]


def extract_accessory_image_fallback(
    product_id: int,
    options: dict,
    product_images: list[str],
) -> list[dict]:
    """Use a product image only when the accessory color relationship is unambiguous."""
    primary_image = next(
        (image for value in product_images if (image := product_image_url(value))),
        None,
    )
    if primary_image is None:
        return []

    color_groups = [
        group for group in options.get("basic", [])
        if not group.get("isDeleted")
        and str(group.get("name") or "").strip().casefold()
        in {"컬러", "색상", "color", "colour"}
    ]
    if len(color_groups) > 1:
        return []
    if not color_groups:
        return [{
            "product_id": product_id,
            "color_raw": None,
            "color_status": "unspecified",
            "image_url": primary_image,
            "evidence": "Detail.primaryImage.colorUnspecified",
        }]

    group = color_groups[0]
    if type(group.get("no")) is not int:
        return []
    linked_values = set()
    for item in options.get("optionItems", []):
        if (item.get("goodsNo") != product_id or item.get("activated") is not True
                or item.get("isDeleted")):
            continue
        for value in item.get("optionValues", []):
            if (value.get("optionNo") == group["no"] and type(value.get("no")) is int
                    and value["no"] in (item.get("optionValueNos") or [])):
                linked_values.add(value["no"])
    values = [
        value for value in group.get("optionValues", [])
        if type(value.get("no")) is int and value["no"] in linked_values
        and value.get("optionNo") == group["no"] and not value.get("isDeleted")
        and isinstance(value.get("name"), str) and value["name"].strip()
    ]
    if len(values) != 1:
        return []
    value = values[0]
    return [{
        "product_id": product_id,
        "color_raw": value["name"].strip(),
        "color_status": "declared_single_option",
        "image_url": primary_image,
        "evidence": "Options.basic.singleColor+Detail.primaryImage",
        "source_option_group_id": group["no"],
        "source_option_value_id": value["no"],
    }]
