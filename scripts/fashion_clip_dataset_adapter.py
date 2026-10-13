"""Prepare verified color products for the unchanged fashion-CLIP indexer.

The crawler's color export is a candidate dataset. This adapter never guesses
which product image or measurement belongs to a color variant.
"""

from __future__ import annotations

import argparse
import json
import math
import uuid
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


MEASUREMENT_KEYS = {
    "상의": {"총장", "어깨너비", "가슴단면", "소매길이", "밑단단면", "소매부리단면", "암홀"},
    "아우터": {"총장", "어깨너비", "가슴단면", "소매길이", "밑단단면", "소매부리단면", "암홀"},
    "하의": {"총장", "허리단면", "엉덩이단면", "허벅지단면", "밑위", "밑단단면"},
    "신발": {"발길이", "발볼", "발목높이", "굽높이"},
    "모자": {"머리둘레", "챙길이", "깊이"},
}


def is_http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def numeric_product_id(candidate_id: object) -> int | None:
    try:
        parsed = uuid.UUID(str(candidate_id))
    except (TypeError, ValueError, AttributeError):
        return None
    return (parsed.int & ((1 << 63) - 1)) or 1


def verified_measurements(product: dict, category: str) -> list[dict]:
    if product.get("measurement_unit") != "cm":
        return []
    rows = []
    for sequence, option in enumerate(product.get("sizes") or []):
        if option.get("measurement_status") != "label_match" or not option.get("size"):
            continue
        measurements = {
            key: float(value)
            for key, value in option.items()
            if key in MEASUREMENT_KEYS[category]
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value > 0
        }
        if measurements:
            rows.append({
                "size": option["size"],
                "sequence": sequence,
                "measurements": measurements,
            })
    return rows


def adapt_product(product: dict) -> tuple[dict | None, list[str]]:
    reasons = []
    category = (product.get("dataset") or {}).get("logical_category")
    if category not in MEASUREMENT_KEYS:
        reasons.append("invalid_category")

    mapped_id = numeric_product_id(product.get("product_id"))
    if mapped_id is None or type(product.get("source_product_id")) is not int:
        reasons.append("invalid_identity")

    thumbnail = product.get("thumbnail_url")
    if product.get("thumbnail_status") != "verified" or not is_http_url(thumbnail):
        reasons.append("thumbnail_not_verified")

    price = (product.get("price") or {}).get("normal")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        reasons.append("invalid_price")

    sizes = verified_measurements(product, category) if category in MEASUREMENT_KEYS else []
    if not sizes:
        reasons.append("no_verified_measurements")

    if reasons:
        return None, reasons

    adapted = {
        "source": product.get("source"),
        "source_url": product.get("source_url"),
        "product_id": mapped_id,
        "source_product_id": product["source_product_id"],
        "color_candidate_id": product["product_id"],
        "color": product.get("color"),
        "name": product.get("name"),
        "brand": product.get("brand"),
        "category": product.get("category"),
        "dataset": product.get("dataset"),
        "season": product.get("season"),
        "price": product.get("price"),
        "features": product.get("features"),
        "images": [thumbnail],
        "size": {"unit": "cm", "measurements": sizes},
    }
    return adapted, []


def export_dataset(source_root: Path, output_root: Path) -> dict:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if not source_root.is_dir():
        raise ValueError(f"Source directory does not exist: {source_root}")
    if source_root == output_root or source_root in output_root.parents or output_root in source_root.parents:
        raise ValueError("Source and output directories must not overlap")
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"Output directory must be empty: {output_root}")

    paths = sorted(source_root.glob("*/*.json"))
    if not paths:
        raise ValueError(f"No candidate JSON files found: {source_root}")

    products = []
    excluded = []
    reason_counts: Counter[str] = Counter()
    seen_ids: set[int] = set()
    for path in paths:
        candidate = json.loads(path.read_text(encoding="utf-8"))
        adapted, reasons = adapt_product(candidate)
        if adapted is None:
            reason_counts.update(reasons)
            excluded.append({"file": str(path.relative_to(source_root)).replace("\\", "/"), "reasons": reasons})
            continue
        product_id = adapted["product_id"]
        if product_id in seen_ids:
            raise ValueError(f"Numeric product ID collision: {product_id}")
        seen_ids.add(product_id)
        products.append(adapted)

    output_root.mkdir(parents=True, exist_ok=True)
    for product in products:
        category = product["dataset"]["logical_category"]
        destination = output_root / "data" / category / f"{product['product_id']}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(product, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "input_count": len(paths),
        "exported_count": len(products),
        "excluded_count": len(excluded),
        "exclusion_reasons": dict(sorted(reason_counts.items())),
        "ready_for_indexing": bool(products),
        "products": [
            {
                "product_id": product["product_id"],
                "color_candidate_id": product["color_candidate_id"],
                "source_product_id": product["source_product_id"],
                "color": product["color"],
                "verified_size_count": len(product["size"]["measurements"]),
            }
            for product in products
        ],
        "excluded": excluded,
    }
    (output_root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Crawler color_products/candidates directory")
    parser.add_argument("--output", required=True, type=Path, help="Empty, separate output directory")
    args = parser.parse_args()
    report = export_dataset(args.source, args.output)
    print(json.dumps({key: value for key, value in report.items() if key not in {"products", "excluded"}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
