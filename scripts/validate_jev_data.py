"""Validate crawler JSON against FashionCLIP's Jev input contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


class ContractError(ValueError):
    """Raised when crawler output cannot enter the Jev stage."""


def validate_jev_data(source_root: Path) -> dict[str, int]:
    source_root = source_root.resolve()
    if not source_root.is_dir():
        raise ContractError(f"source directory does not exist: {source_root}")

    paths = sorted(source_root.rglob("*.json"))
    if not paths:
        raise ContractError(f"no product JSON files found: {source_root}")

    normalized_colors: set[str] = set()
    products_with_colors = 0
    for path in paths:
        try:
            product = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"{path}: invalid JSON: {exc}") from exc
        if not isinstance(product, dict):
            raise ContractError(f"{path}: product JSON root must be an object")

        name = product.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ContractError(f"{path}: name must be a non-empty string")

        dataset = product.get("dataset")
        if not isinstance(dataset, dict):
            raise ContractError(f"{path}: dataset must be an object")
        logical_category = dataset.get("logical_category")
        if not isinstance(logical_category, str) or not logical_category.strip():
            raise ContractError(f"{path}: dataset.logical_category must be a non-empty string")

        mappings = product.get("color_image_mappings", [])
        if not isinstance(mappings, list):
            raise ContractError(f"{path}: color_image_mappings must be an array")
        if mappings:
            products_with_colors += 1

        for mapping in mappings:
            if not isinstance(mapping, dict):
                raise ContractError(f"{path}: color_image_mappings[] must be an object")
            raw = mapping.get("color_raw")
            if not isinstance(raw, str) or not raw.strip():
                raise ContractError(f"{path}: color_image_mappings[].color_raw must be a non-empty string")
            normalized_colors.add(raw.strip().lower())

    if not normalized_colors:
        raise ContractError("crawler output contains no color_image_mappings")

    return {
        "source_product_count": len(paths),
        "products_with_colors": products_with_colors,
        "unique_color_count": len(normalized_colors),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path, help="Crawler data directory")
    args = parser.parse_args()
    print(json.dumps(validate_jev_data(args.source), ensure_ascii=False))


if __name__ == "__main__":
    main()
