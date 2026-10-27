"""Offline raw-to-Jev selection. Never guesses colors or grants indexing approval."""

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import io
import json
import math
from pathlib import Path
import tarfile
from urllib.parse import urlparse

from src.collector.config import CATEGORY_CONFIG
from src.collector.rules import (
    ACCESSORY_FALLBACK_CATEGORIES,
    is_allowed_gender,
    logical_category,
)
from src.collector.season_allocator import possible_seasons
from src.collector.select_balanced import Dinic, SEASONS

IMAGE_HOSTS = {"image.msscdn.net", "image.musinsa.com", "image.musinsa.co.kr"}
MEASUREMENTS = {
    "상의": {"총장", "어깨너비", "가슴단면", "소매길이", "밑단단면", "소매부리단면", "암홀"},
    "아우터": {"총장", "어깨너비", "가슴단면", "소매길이", "밑단단면", "소매부리단면", "암홀"},
    "하의": {"총장", "허리단면", "엉덩이단면", "허벅지단면", "밑위", "밑단단면"},
    "신발": {"발길이", "발볼", "발목높이", "굽높이"},
    "모자": {"머리둘레", "챙길이", "깊이"},
}


def external_product_contract(product: dict) -> dict:
    """Return the original downstream JSON shape after internal fallback handling."""
    item = deepcopy(product)
    size = item.get("size")
    if isinstance(size, dict):
        size.pop("source", None)
        options = size.pop("options", [])
        if not size.get("measurements") and isinstance(options, list):
            size["measurements"] = [
                {"size": str(option.get("size") or "").strip(),
                 "sequence": index, "measurements": {}}
                for index, option in enumerate(options, 1)
                if isinstance(option, dict) and str(option.get("size") or "").strip()
            ]
    mappings = item.get("color_image_mappings")
    if isinstance(mappings, list):
        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue
            mapping.pop("color_status", None)
            if not isinstance(mapping.get("color_raw"), str) or not mapping["color_raw"].strip():
                mapping["color_raw"] = "미지정"
    return item


def validate_product(product: dict) -> tuple[str, str]:
    identifier = str(product.get("product_id", ""))
    if not identifier.isascii() or not identifier.isdecimal() or int(identifier) <= 0:
        raise ValueError("invalid_product_id")
    category = logical_category(product)
    if category not in CATEGORY_CONFIG:
        raise ValueError("unknown_category")
    declared = (product.get("dataset") or {}).get("logical_category")
    if declared is not None and declared != category:
        raise ValueError("category_mismatch")
    if not is_allowed_gender(product):
        raise ValueError("gender_not_allowed")
    size = product.get("size") or {}
    rows = size.get("measurements") or []
    if (category in ACCESSORY_FALLBACK_CATEGORIES
            and size.get("source") == "sales_option"):
        options = size.get("options") or []
        if (size.get("available") is not True
                or size.get("unit") not in {"mm", "label"}
                or not options
                or not all(str(item.get("size") or "").strip() for item in options)):
            raise ValueError("invalid_accessory_size_options")
    else:
        if size.get("available") is not True or size.get("unit") != "cm" or not rows:
            raise ValueError("actual_size_missing_or_wrong_unit")
        for row in rows:
            measurements = row.get("measurements") or {}
            if not row.get("size") or not any(
                key in MEASUREMENTS[category] and isinstance(value, (int, float))
                and not isinstance(value, bool) and math.isfinite(value) and value > 0
                for key, value in measurements.items()
            ):
                raise ValueError("invalid_actual_size")
    mappings = product.get("color_image_mappings")
    if not isinstance(mappings, list) or not mappings:
        raise ValueError("color_image_mappings_missing")
    seen = set()
    for mapping in mappings:
        raw, url = mapping.get("color_raw"), mapping.get("image_url")
        evidence = mapping.get("evidence")
        unspecified_accessory = (
            category in ACCESSORY_FALLBACK_CATEGORIES
            and raw is None
            and mapping.get("color_status") == "unspecified"
            and evidence == "Detail.primaryImage.colorUnspecified"
        )
        if ((not unspecified_accessory
             and (not isinstance(raw, str) or not raw.strip()))
                or not isinstance(url, str)):
            raise ValueError("invalid_color_image_mapping")
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname not in IMAGE_HOSTS
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise ValueError("unapproved_image_url")
        if str(mapping.get("product_id", "")) != identifier or not evidence:
            raise ValueError("color_image_evidence_missing")
        pair = (raw.strip().lower() if isinstance(raw, str) else None, url)
        if pair in seen:
            raise ValueError("duplicate_color_image_mapping")
        seen.add(pair)
    return str(int(identifier)), category


def select_products(products: list[dict], category: str) -> list[dict]:
    config = CATEGORY_CONFIG[category]
    if not config.get("season_balance_required", True):
        selected = deepcopy(products[:config["total_quota"]])
        for product in selected:
            candidates, source = possible_seasons(product)
            product.setdefault("season", {}).update(primary=candidates[0] if candidates else None,
                primary_candidates=candidates, primary_source=source)
        return selected
    source, start = 0, 1
    season_start = start + len(products)
    sink = season_start + len(SEASONS)
    graph = Dinic(sink + 1)
    for index, product in enumerate(products):
        graph.add_edge(source, start + index, 1)
        candidates, _ = possible_seasons(product)
        for season in candidates:
            graph.add_edge(start + index, season_start + SEASONS.index(season), 1)
    for index, season in enumerate(SEASONS):
        graph.add_edge(season_start + index, sink, config["season_quota"][season])
    graph.max_flow(source, sink)
    selected = []
    for index, product in enumerate(products):
        for edge in graph.graph[start + index]:
            if season_start <= edge.to < sink and edge.cap == 0:
                item = deepcopy(product)
                candidates, origin = possible_seasons(item)
                item.setdefault("season", {}).update(primary=SEASONS[edge.to - season_start],
                    primary_candidates=candidates, primary_source=origin)
                selected.append(item)
                break
    return selected


def prepare(sources: list[Path]) -> tuple[dict, dict[str, bytes]]:
    groups = {category: [] for category in CATEGORY_CONFIG}
    seen, rejected = set(), Counter()
    for source in sources:
        if not source.is_dir() or source.is_symlink():
            raise ValueError("Source must be an existing non-symlink directory")
        for path in sorted(source.rglob("*.json")):
            if any(parent.is_symlink() for parent in (path, *path.parents)):
                raise ValueError("Source symlinks are not permitted")
            product = json.loads(path.read_text(encoding="utf-8"))
            try:
                identifier, category = validate_product(product)
            except ValueError as error:
                rejected[str(error)] += 1
                continue
            if identifier in seen:
                raise ValueError("Duplicate product ID across sources")
            seen.add(identifier)
            groups[category].append(product)
    selected, counts, season_counts = [], {}, {}
    for category, products in groups.items():
        items = select_products(products, category)
        counts[category] = len(items)
        season_counts[category] = dict(Counter(item["season"]["primary"] for item in items
                                             if item["season"]["primary"]))
        for item in items:
            item.setdefault("dataset", {}).update(logical_category=category,
                primary_season=item["season"]["primary"], gender_scope="MALE_AND_UNISEX")
        selected.extend(external_product_contract(item) for item in items)
    files = {f"data/{item['dataset']['logical_category']}/{int(item['product_id'])}.json":
             (json.dumps(item, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
             for item in selected}
    deficits = {category: config["total_quota"] - counts[category]
                for category, config in CATEGORY_CONFIG.items()}
    report = {"schema_version": 1, "ready_for_jev": not any(deficits.values()),
              "approved_for_indexing": False, "image_contents_verified": False,
              "selected_count": len(selected), "selected_by_category": counts,
              "season_counts": season_counts, "deficits": deficits, "rejected_by_reason": dict(rejected),
              "files": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}}
    return report, files


def write_bundle(destination: Path, report: dict, files: dict[str, bytes]) -> None:
    if not report["ready_for_jev"]:
        raise ValueError("Dataset quotas are incomplete; refusing Jev bundle")
    if report["files"] != {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}:
        raise ValueError("Curated data changed after validation")
    with destination.open("xb") as output, tarfile.open(fileobj=output, mode="w:gz") as archive:
        entries = dict(files, **{"config/curation_report.json":
            json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")})
        for name, data in sorted(entries.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()
    report, files = prepare(args.source)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.bundle:
        write_bundle(args.bundle, report, files)


if __name__ == "__main__":
    main()
