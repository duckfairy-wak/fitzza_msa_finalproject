"""Select measured products whose color has a source-backed product photo."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from scripts.audit_color_thumbnail_links import RateLimit, check_image, full_image_url, OPTION_SIZE_SUFFIX


CATEGORIES = ("상의", "하의", "신발", "아우터", "모자")
COLOR_GROUP_TERMS = ("컬러", "색상", "color", "colour")
SIZE_GROUP_TERMS = ("사이즈", "size")
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
    r"(?<![A-Z가-힣])(?:" + "|".join(re.escape(value) for value in sorted(COLOR_ALIASES, key=len, reverse=True)) + r")(?![A-Z가-힣])"
)


def color_matches(value: object) -> list[str]:
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or "")).upper())
    return [match.group() for match in COLOR_PATTERN.finditer(normalized)]


def color_tokens(value: object) -> set[str]:
    return {COLOR_ALIASES[match] for match in color_matches(value)}


def title_color(product: dict) -> str | None:
    matches = [match for title in (product.get("name"), product.get("name_en"))
               for match in color_matches(title)]
    return matches[0] if len({COLOR_ALIASES[match] for match in matches}) == 1 else None


def measured(product: dict) -> bool:
    return any(
        isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0
        for row in (product.get("size") or {}).get("measurements") or []
        for value in (row.get("measurements") or {}).values()
    )


def declared_option_colors(source: dict) -> set[str]:
    labels = set()
    for group in (source.get("option_data") or {}).get("basic", []):
        group_name = str(group.get("name") or "").lower()
        is_color = any(term in group_name for term in COLOR_GROUP_TERMS)
        is_size = any(term in group_name for term in SIZE_GROUP_TERMS)
        for value in group.get("optionValues", []):
            label = str(value.get("name") or "").strip()
            split = OPTION_SIZE_SUFFIX.fullmatch(label)
            if split and (is_color or is_size):
                labels.add(split.group(1).strip())
            elif is_color and not is_size and label:
                labels.add(label)
    return labels


def has_other_choices(product: dict, source: dict) -> bool:
    for group in source.get("option_data", {}).get("basic", []):
        name = str(group.get("name") or "").lower()
        values = group.get("optionValues") or []
        if len(values) > 1 and not any(term in name for term in SIZE_GROUP_TERMS):
            return True
        if any(color_tokens(value.get("name")) for value in values):
            return True
    for group in product.get("options") or []:
        name = str(group.get("name") or "").lower()
        if len(group.get("values") or []) > 1 and not any(term in name for term in SIZE_GROUP_TERMS):
            return True
    return False


def verified(checks: dict, url: str | None) -> bool:
    return bool(url and (checks.get(url) or {}).get("reachable_image"))


def mapped_option_colors(source: dict, checks: dict) -> dict[str, str]:
    links = defaultdict(set)
    for link in source.get("color_image_links", []):
        if link.get("scope") == "source_option" and verified(checks, link.get("image_url")):
            links[link["color_raw"]].add(link["image_url"])
    return {color: sorted(urls)[0] for color, urls in links.items() if urls}


def same_brand_related(product: dict, source: dict, checks: dict) -> list[dict]:
    brand_id = (product.get("brand") or {}).get("id")
    if not brand_id:
        return []
    related = []
    for tab in (source.get("other_color_data") or {}).get("curationTabs", []):
        if tab.get("curationType") != "OTHER_COLOR":
            continue
        for item in tab.get("curationGoodsList", []):
            url = full_image_url(item.get("imageUrl"))
            if (item.get("goodsNo") != product["product_id"] and item.get("brand") == brand_id
                    and item.get("displayColorText") and verified(checks, url)):
                related.append({
                    "product_id": item["goodsNo"], "color_raw": item["displayColorText"],
                    "image_url": url, "brand_id": brand_id,
                    "evidence": "OtherColorGoods.OTHER_COLOR",
                })
    return list({row["product_id"]: row for row in related}.values())


def own_other_color(product: dict, source: dict, checks: dict) -> list[dict]:
    return [
        {"product_id": product["product_id"], "color_raw": link["color_raw"],
         "image_url": link["image_url"], "evidence": link["evidence"]}
        for link in source.get("color_image_links", [])
        if link.get("scope") == "source_product" and verified(checks, link.get("image_url"))
    ]


def classify(product: dict, source: dict, checks: dict) -> dict | None:
    if source.get("status") != "ok" or not measured(product):
        return None
    if (product.get("gender") or {}).get("normalized") not in {"MALE", "UNISEX"}:
        return None
    category = (product.get("dataset") or {}).get("logical_category")
    if category not in CATEGORIES:
        return None

    pid = product["product_id"]
    thumbnail = full_image_url((source.get("product_image_urls") or [None])[0])
    title = title_color(product)
    declared = declared_option_colors(source)
    options = mapped_option_colors(source, checks)
    own = own_other_color(product, source, checks)
    siblings = same_brand_related(product, source, checks)
    links = source.get("color_image_links", [])
    has_linked_color = any(link.get("scope") == "linked_product" for link in links)

    if title and not has_other_choices(product, source) and not has_linked_color and verified(checks, thumbnail):
        return {"priority": 1, "reason": "single_product_title_color", "mappings": [
            {"product_id": pid, "color_raw": title, "image_url": thumbnail,
             "evidence": "Detail.thumbnailImageUrl+product_name"}], "related": []}

    if declared and declared <= options.keys() and len({options[color] for color in declared}) == len(declared):
        return {"priority": 2, "reason": "complete_color_dropdown_images", "mappings": [
            {"product_id": pid, "color_raw": color, "image_url": options[color],
             "evidence": "Options.basic.optionValues.imageUrl"}
            for color in sorted(declared)], "related": []}

    if own and siblings:
        return {"priority": 3, "reason": "same_brand_linked_color_products", "mappings": own,
                "related": siblings}

    if title and verified(checks, thumbnail):
        return {"priority": 4, "reason": "title_color_fallback", "mappings": [
            {"product_id": pid, "color_raw": title, "image_url": thumbnail,
             "evidence": "Detail.thumbnailImageUrl+product_name"}], "related": []}
    return None


def load_products(path: Path) -> list[dict]:
    with zipfile.ZipFile(path) as archive:
        return [json.loads(archive.read(name)) for name in sorted(archive.namelist()) if name.endswith(".json")]


def prepare_checks(products: list[dict], sources: dict[int, dict], evidence_dir: Path, output: Path) -> dict:
    checks_path = evidence_dir / "image_checks.json"
    checks = json.loads(checks_path.read_text(encoding="utf-8")) if checks_path.exists() else {}
    thumbnail_checks_path = output / "thumbnail_checks.json"
    if thumbnail_checks_path.exists():
        checks.update(json.loads(thumbnail_checks_path.read_text(encoding="utf-8")))
    thumbnails = set()
    for product in products:
        if not title_color(product):
            continue
        source = sources.get(product["product_id"], {})
        gallery = source.get("product_image_urls") or []
        if gallery:
            url = full_image_url(gallery[0])
            if url:
                thumbnails.add(url)
    limiter = RateLimit(0.4)
    pending = sorted(url for url in thumbnails if url not in checks)
    for index, url in enumerate(pending, 1):
        checks[url] = check_image(url, limiter)
        if index % 100 == 0:
            print("thumbnail_checks", index, "/", len(pending), flush=True)
    thumbnail_checks_path.write_text(json.dumps({url: checks[url] for url in thumbnails}, ensure_ascii=False, indent=2), encoding="utf-8")
    return checks


def run(args: argparse.Namespace) -> dict:
    args.output.mkdir(parents=True, exist_ok=True)
    products = load_products(args.source_zip)
    sources = {}
    for product in products:
        path = args.evidence_dir / "sources" / f"{product['product_id']}.json"
        if path.exists():
            sources[product["product_id"]] = json.loads(path.read_text(encoding="utf-8"))
    checks = prepare_checks(products, sources, args.evidence_dir, args.output)
    candidates = defaultdict(list)
    rejected = Counter()
    for product in products:
        source = sources.get(product["product_id"], {})
        result = classify(product, source, checks)
        if result:
            candidates[product["dataset"]["logical_category"]].append((product, result))
        else:
            rejected[product["dataset"]["logical_category"]] += 1

    selected_counts = {}
    available = {}
    priority_counts = Counter()
    used_urls = set()
    for category in CATEGORIES:
        rows = sorted(candidates[category], key=lambda item: (item[1]["priority"], item[0]["product_id"]))
        available[category] = len(rows)
        selected = rows[:args.per_category]
        selected_counts[category] = len(selected)
        destination = args.output / "data" / category
        destination.mkdir(parents=True, exist_ok=True)
        for product, decision in selected:
            priority_counts[decision["priority"]] += 1
            used_urls.update(row["image_url"] for row in decision["mappings"] + decision["related"])
            enriched = {**product, "color_image_mappings": decision["mappings"],
                        "related_color_products": decision["related"],
                        "color_collection": {"priority": decision["priority"],
                                             "reason": decision["reason"],
                                             "image_verified_by": "GET_response_and_file_signature",
                                             "checked_at": datetime.now(timezone.utc).isoformat()}}
            (destination / f"{product['product_id']}.json").write_text(
                json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"source_count": len(products), "requested_per_category": args.per_category,
              "selected_by_category": selected_counts, "qualified_available_by_category": available,
              "selected_by_priority": dict(sorted(priority_counts.items())),
              "rejected_by_category": dict(rejected),
              "source_page_count": len(sources)}
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output / "image_checks.json").write_text(
        json.dumps({url: checks[url] for url in sorted(used_urls)}, ensure_ascii=False, indent=2), encoding="utf-8")
    with zipfile.ZipFile(args.output / "color_qualified_pilot.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(args.output / "report.json", "report.json")
        archive.write(args.output / "image_checks.json", "image_checks.json")
        for path in sorted((args.output / "data").rglob("*.json")):
            archive.write(path, "data/" + path.relative_to(args.output / "data").as_posix())
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-category", type=int, default=20)
    print(json.dumps(run(parser.parse_args()), ensure_ascii=False))
