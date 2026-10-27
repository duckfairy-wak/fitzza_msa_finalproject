from __future__ import annotations

from typing import Any


def _full_image_url(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("//"):
        return f"https:{url}"
    return url


def normalize_actual_size(data: dict[str, Any] | None) -> dict[str, Any]:
    """
    무신사 actual-size API 응답을 서비스용 범용 구조로 변환한다.

    상의/하의마다 실측 항목명이 달라질 수 있으므로
    총장, 허리단면 등을 코드에 고정하지 않고 measurements dict로 보관한다.
    """
    if not data:
        return {
            "available": False,
            "source": "actual_measurement",
            "type_name": None,
            "type_number": None,
            "unit": "cm",
            "description": None,
            "guide_image": None,
            "measurements": [],
        }

    rows: list[dict[str, Any]] = []

    for size in data.get("sizes", []):
        measurements = {
            item.get("name"): item.get("value")
            for item in size.get("items", [])
            if item.get("name")
        }

        rows.append(
            {
                "size": size.get("name"),
                "sequence": size.get("sequence"),
                "measurements": measurements,
            }
        )

    return {
        "available": bool(rows),
        "source": "actual_measurement",
        "type_name": data.get("typeName"),
        "type_number": data.get("typeNumber"),
        "unit": "cm",
        "description": data.get("description"),
        "guide_image": _full_image_url(data.get("webImage")),
        "measurements": rows,
    }


def normalize_accessory_option_size(product: dict[str, Any]) -> dict[str, Any]:
    """Preserve purchasable accessory sizes when no measurement table is published."""
    values: list[dict[str, Any]] = []
    seen: set[str] = set()
    option_name = None

    for option in product.get("options") or []:
        name = str(option.get("name") or "").strip()
        normalized_name = name.casefold()
        if "사이즈" not in name and "size" not in normalized_name:
            continue
        option_name = name
        for item in option.get("values") or []:
            label = str(item.get("name") or "").strip()
            if not label or label in seen:
                continue
            seen.add(label)
            values.append({
                "size": label,
                "code": str(item.get("code") or label),
            })

    numeric_millimeters = bool(values) and all(
        value["size"].isdigit() and 100 <= int(value["size"]) <= 400
        for value in values
    )
    return {
        "available": bool(values),
        "source": "sales_option",
        "type_name": option_name,
        "type_number": None,
        "unit": "mm" if numeric_millimeters else "label",
        "description": "Purchasable accessory size options from the product page",
        "guide_image": None,
        "measurements": [],
        "options": values,
    }
