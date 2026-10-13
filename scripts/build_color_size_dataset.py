"""Project product colors across its measured sizes without using stock state.

This produces a reviewable data contract, not an input for the current Qdrant
indexer. Source JSON files are never modified.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
import uuid
import zipfile
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path


COLOR_ALIASES = {
    "BLACK": "black", "블랙": "black", "검정": "black",
    "WHITE": "white", "화이트": "white", "흰색": "white",
    "IVORY": "ivory", "아이보리": "ivory", "CREAM": "cream", "크림": "cream",
    "NAVY": "navy", "네이비": "navy", "남색": "navy",
    "BLUE": "blue", "블루": "blue", "SKY": "sky", "연청": "light_blue",
    "중청": "medium_blue", "진청": "dark_blue", "흑청": "black_denim",
    "GREEN": "green", "그린": "green", "KHAKI": "khaki", "카키": "khaki",
    "OLIVE": "olive", "올리브": "olive", "BROWN": "brown", "브라운": "brown", "갈색": "brown",
    "BEIGE": "beige", "베이지": "beige", "GRAY": "gray", "GREY": "gray",
    "그레이": "gray", "회색": "gray", "CHARCOAL": "charcoal", "차콜": "charcoal",
    "PINK": "pink", "핑크": "pink", "RED": "red", "레드": "red",
    "PURPLE": "purple", "퍼플": "purple", "YELLOW": "yellow", "옐로우": "yellow",
    "ORANGE": "orange", "오렌지": "orange", "WINE": "wine", "와인": "wine",
    "BURGUNDY": "burgundy", "버건디": "burgundy", "SILVER": "silver", "실버": "silver",
    "GOLD": "gold", "골드": "gold", "MINT": "mint", "민트": "mint",
    "ECRU": "ecru", "에크루": "ecru", "TAN": "tan", "탄": "tan",
}
COLOR_PATTERN = re.compile(
    r"(?<![A-Z가-힣])(?:" + "|".join(re.escape(x) for x in sorted(COLOR_ALIASES, key=len, reverse=True)) + r")(?![A-Z가-힣])"
)
SIZE_SUFFIX = re.compile(
    r"(?:[2-5]?X{0,3}[SML]|FREE|ONE\s*SIZE|OS|F|\d{1,3}(?:\.5)?(?:호|MM|CM)?)$",
    re.IGNORECASE,
)


def normalize(value: object) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or "")).upper()).strip()


def color_tokens(value: object) -> set[str]:
    return {COLOR_ALIASES[match.group()] for match in COLOR_PATTERN.finditer(normalize(value))}


def colors_for_product(product: dict) -> tuple[list[str], str]:
    structured = set()
    for group in product.get("options") or []:
        name = normalize(group.get("name"))
        if any(term in name for term in ("컬러", "색상", "COLOR", "COLOUR")):
            for value in group.get("values") or []:
                structured.update(color_tokens(value.get("name")))
    for option in product.get("option_items") or []:
        for value in option.get("values") or []:
            structured.update(color_tokens(value))
    if structured:
        return sorted(structured), "structured_option"

    title = color_tokens(product.get("name")) | color_tokens(product.get("name_en"))
    if title:
        return sorted(title), "title_keyword_review"
    return [], "unresolved"


def split_size_label(raw_label: object) -> tuple[str | None, str]:
    text = normalize(raw_label)
    for divider in (" - ", "-", "/", "_"):
        if divider in text:
            prefix, suffix = text.rsplit(divider, 1)
            if SIZE_SUFFIX.fullmatch(suffix.strip()):
                matches = color_tokens(prefix)
                if len(matches) == 1:
                    return next(iter(matches)), suffix.strip()
    return None, text


def measured_rows(product: dict) -> list[dict]:
    rows = []
    for index, source in enumerate((product.get("size") or {}).get("measurements") or []):
        values = source.get("measurements") or {}
        if not any(type(value) in (int, float) and value > 0 for value in values.values()):
            continue
        raw_label = str(source.get("size") or "")
        row_color, size = split_size_label(raw_label)
        rows.append({
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"musinsa:size:{product['product_id']}:{index}:{raw_label}")),
            "raw_label": raw_label,
            "size": size,
            "row_color": row_color,
            "sequence": source.get("sequence", index),
            "values": deepcopy(values),
        })
    return rows


def choose_measurement(rows: list[dict], color: str) -> tuple[str | None, str]:
    exact = [row for row in rows if row["row_color"] == color]
    if len(exact) == 1:
        return exact[0]["id"], "color_row"
    shared = [row for row in rows if row["row_color"] is None]
    if len(shared) == 1:
        return shared[0]["id"], "product_size_chart"
    unique_values = {json.dumps(row["values"], sort_keys=True, ensure_ascii=False) for row in rows}
    if rows and len(unique_values) == 1:
        return rows[0]["id"], "identical_size_values"
    return None, "ambiguous_measurement"


def project_product(source: dict) -> tuple[dict, dict]:
    product = deepcopy(source)
    colors, color_source = colors_for_product(source)
    rows = measured_rows(source)
    by_size = defaultdict(list)
    for row in rows:
        by_size[row["size"]].append(row)

    variants = []
    for color in colors:
        options = []
        for size, size_rows in sorted(by_size.items()):
            measurement_id, relation = choose_measurement(size_rows, color)
            options.append({"size": size, "measurement_id": measurement_id, "relation_source": relation})
        variants.append({
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"musinsa:color:{source['product_id']}:{color}")),
            "color": {"name": color, "source": color_source},
            "images": [],
            "options": options,
        })

    product["schema_version"] = "2.1-color-size-projection"
    product["size"]["measurements"] = rows
    product["variants"] = variants
    product["projection"] = {
        "color_source": color_source,
        "stock_used": False,
        "variant_image_verified": False,
    }
    audit = {
        "product_id": source["product_id"],
        "color_source": color_source,
        "color_count": len(colors),
        "measured_size_count": len(by_size),
        "combination_count": sum(len(item["options"]) for item in variants),
        "unlinked_count": sum(option["measurement_id"] is None for item in variants for option in item["options"]),
    }
    return product, audit


def build_dataset(source_zip: Path, output_root: Path) -> dict:
    if not source_zip.is_file():
        raise FileNotFoundError(source_zip)
    if output_root.exists() and any(output_root.iterdir()):
        raise ValueError(f"Output directory must be empty: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    audits = []
    with zipfile.ZipFile(source_zip) as source:
        names = sorted(name for name in source.namelist() if name.endswith(".json"))
        for name in names:
            product, audit = project_product(json.loads(source.read(name).decode("utf-8")))
            category = product["dataset"]["logical_category"]
            destination = output_root / "data" / category / f"{product['product_id']}.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(product, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            audits.append(audit)
    if len(audits) != 500 or len({item["product_id"] for item in audits}) != len(audits):
        raise ValueError("Expected 500 distinct source products")
    counts = Counter(item["color_source"] for item in audits)
    report = {
        "source_products": len(audits),
        "output_products": len(audits),
        "color_source_counts": dict(counts),
        "products_with_measured_sizes": sum(item["measured_size_count"] > 0 for item in audits),
        "products_with_color_size_candidates": sum(item["combination_count"] > 0 for item in audits),
        "products_with_all_combinations_linked": sum(item["combination_count"] > 0 and item["unlinked_count"] == 0 for item in audits),
        "candidate_combinations": sum(item["combination_count"] for item in audits),
        "unlinked_combinations": sum(item["unlinked_count"] for item in audits),
        "products": audits,
    }
    (output_root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive = output_root / "color_size_dataset.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted((output_root / "data").rglob("*.json")):
            bundle.write(path, path.relative_to(output_root).as_posix())
        bundle.write(output_root / "report.json", "report.json")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = build_dataset(args.source_zip, args.output)
    print(json.dumps({key: value for key, value in report.items() if key != "products"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
