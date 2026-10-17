"""Expand the color-qualified pilot to an equal-size category dataset."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from scripts.audit_color_thumbnail_links import (
    HEADERS,
    RateLimit,
    check_image,
    extract_evidence,
    extract_option_links,
    full_image_url,
)
from scripts.collect_color_qualified_pilot import CATEGORIES, EXCLUDED_PRODUCTS, classify, load_products


CATEGORY_NAMES = {"상의": "상의", "바지": "하의", "하의": "하의", "신발": "신발", "아우터": "아우터", "모자": "모자"}


def logical_category(product: dict) -> str | None:
    category = product.get("category") or {}
    return CATEGORY_NAMES.get(category.get("categoryDepth1Name") or category.get("categoryDepth1Title"))


def complete_metadata(product: dict) -> dict:
    category = logical_category(product)
    season = product.setdefault("season", {})
    original = season.get("original") or []
    collection = (season.get("collection") or {}).get("type")
    if original:
        primary = original[0]
        candidates = original
        source = "original_tag"
    elif collection == "SS":
        primary, candidates, source = "봄", ["봄", "여름"], "collection_fallback"
    elif collection == "FW":
        primary, candidates, source = "가을", ["가을", "겨울"], "collection_fallback"
    else:
        primary, candidates, source = None, [], None
    season["primary"] = primary
    season["primary_source"] = source
    season["primary_candidates"] = candidates
    if category:
        product["dataset"] = {"logical_category": category, "primary_season": primary,
                              "gender_scope": "MALE_AND_UNISEX"}
    return product


def load_sources(products: list[dict], evidence_dir: Path, work_dir: Path | None = None) -> dict[int, dict]:
    sources = {}
    for product in products:
        candidates = [evidence_dir / "sources" / f"{product['product_id']}.json"]
        if work_dir is not None:
            candidates.append(work_dir / "sources" / f"{product['product_id']}.json")
        path = next((candidate for candidate in candidates if candidate.exists()), None)
        if path is None:
            continue
        source = json.loads(path.read_text(encoding="utf-8"))
        source = refresh_source_options(source, product["product_id"])
        path.write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
        sources[product["product_id"]] = source
    return sources


def refresh_source_options(source: dict, product_id: int) -> dict:
    images, links = extract_option_links(source.get("option_data") or {}, product_id)
    source["option_image_links"] = images
    retained_links = []
    for row in source.get("color_image_links", []):
        if row.get("scope") == "source_option":
            continue
        image_url = full_image_url(row.get("image_url"))
        if image_url:
            retained_links.append({**row, "image_url": image_url})
    source["color_image_links"] = retained_links + links
    source["product_image_urls"] = list(dict.fromkeys(
        image_url for value in source.get("product_image_urls", [])
        if (image_url := full_image_url(value))
    ))
    return source


def load_checks(evidence_dir: Path, work_dir: Path) -> dict:
    checks = json.loads((evidence_dir / "image_checks.json").read_text(encoding="utf-8"))
    path = work_dir / "image_checks.json"
    if path.exists():
        merge_image_checks(checks, json.loads(path.read_text(encoding="utf-8")))
    return checks


def authoritative_image_check(check: dict) -> bool:
    return check.get("reachable_image") is True or isinstance(check.get("status"), int)


def merge_image_checks(checks: dict, updates: dict) -> None:
    for url, result in updates.items():
        if authoritative_image_check(result) or url not in checks:
            checks[url] = result


def related_candidates(products: list[dict], sources: dict[int, dict]) -> dict[str, list[int]]:
    source_ids = {product["product_id"] for product in products}
    category_by_id = {product["product_id"]: product["dataset"]["logical_category"] for product in products}
    candidates = defaultdict(dict)
    for source_id, source in sources.items():
        category = category_by_id[source_id]
        for tab in (source.get("other_color_data") or {}).get("curationTabs", []):
            if tab.get("curationType") != "OTHER_COLOR":
                continue
            for item in tab.get("curationGoodsList", []):
                product_id = item.get("goodsNo")
                if product_id and product_id not in source_ids and item.get("displayColorText") and item.get("imageUrl"):
                    candidates[category][int(product_id)] = item.get("reviewCount") or 0
    return {category: [product_id for product_id, _ in sorted(rows.items(), key=lambda row: (-row[1], row[0]))]
            for category, rows in candidates.items()}


def fetch_json(url: str, limiter: RateLimit) -> dict | None:
    for attempt in range(3):
        try:
            limiter.wait()
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return payload.get("data") if isinstance(payload, dict) else None
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                delay = max(float(exc.headers.get("Retry-After", "60")), 60)
                print("rate_limit", url, "backoff", delay, flush=True)
                limiter.defer(delay)
                continue
            return None
        except Exception:
            if attempt == 0:
                time.sleep(2)
                continue
            return None
    return None


def crawl_candidate(product_id: int, crawler_root: Path, work_dir: Path, page_limiter: RateLimit,
                    api_limiter: RateLimit) -> tuple[dict | None, dict | None]:
    product_path = work_dir / "products" / f"{product_id}.json"
    source_path = work_dir / "sources" / f"{product_id}.json"
    if product_path.exists() and source_path.exists():
        product = complete_metadata(json.loads(product_path.read_text(encoding="utf-8")))
        source = refresh_source_options(json.loads(source_path.read_text(encoding="utf-8")), product_id)
        product_path.write_text(json.dumps(product, ensure_ascii=False, indent=2), encoding="utf-8")
        source_path.write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
        return product, source

    if str(crawler_root) not in sys.path:
        sys.path.insert(0, str(crawler_root))
    from src.musinsa_parser import normalize_musinsa_product
    from src.musinsa_size import normalize_actual_size

    url = f"https://www.musinsa.com/products/{product_id}"
    html = None
    for attempt in range(3):
        try:
            page_limiter.wait()
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30) as response:
                html = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                delay = max(float(exc.headers.get("Retry-After", "60")), 60)
                print("rate_limit", product_id, "backoff", delay, flush=True)
                page_limiter.defer(delay)
                continue
            return None, None
        except Exception:
            if attempt == 0:
                time.sleep(2)
                continue
            return None, None
    if not html:
        return None, None
    try:
        product = normalize_musinsa_product(html, url)
        source = extract_evidence(html, product_id)
    except Exception:
        return None, None
    actual_size = fetch_json(f"https://goods-detail.musinsa.com/api2/goods/{product_id}/actual-size", api_limiter)
    product["size"] = normalize_actual_size(actual_size)
    product = complete_metadata(product)
    product_path.parent.mkdir(parents=True, exist_ok=True)
    source_path.parent.mkdir(parents=True, exist_ok=True)
    product_path.write_text(json.dumps(product, ensure_ascii=False, indent=2), encoding="utf-8")
    source_path.write_text(json.dumps(source, ensure_ascii=False, indent=2), encoding="utf-8")
    return product, source


def ensure_checks(source: dict, checks: dict, limiter: RateLimit, work_dir: Path) -> None:
    urls = {link["image_url"] for link in source.get("color_image_links", [])}
    gallery = source.get("product_image_urls") or []
    if gallery:
        urls.add(gallery[0])
    changed = False
    for url in sorted(urls):
        if url not in checks or not authoritative_image_check(checks[url]):
            checks[url] = check_image(url, limiter)
            changed = True
    if changed:
        (work_dir / "image_checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")


def recheck_current_images(output: Path, checks: dict, work_dir: Path) -> None:
    urls = set()
    for path in (output / "data").rglob("*.json") if (output / "data").exists() else []:
        product = json.loads(path.read_text(encoding="utf-8"))
        urls.update(row["image_url"] for row in product.get("color_image_mappings") or [])
        urls.update(row["image_url"] for row in product.get("related_color_products") or [])
    limiter = RateLimit(0.25)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(check_image, url, limiter): url for url in sorted(urls)}
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            url = futures[future]
            merge_image_checks(checks, {url: future.result()})
            if index % 100 == 0:
                print("rechecked_images", index, "/", len(urls), flush=True)
    (work_dir / "image_checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")


def enriched(product: dict, decision: dict) -> dict:
    return {**product, "color_image_mappings": decision["mappings"],
            "related_color_products": decision["related"],
            "color_collection": {"priority": decision["priority"], "reason": decision["reason"],
                                 "image_verified_by": "GET_response_and_file_signature"}}


def write_output(output: Path, selected: dict[str, list[tuple[dict, dict]]], checks: dict,
                 attempted: Counter, per_category: int) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    if (output / "data").exists():
        for path in (output / "data").rglob("*.json"):
            path.unlink()
    used_urls = set()
    priority_counts = Counter()
    for category, rows in selected.items():
        category_dir = output / "data" / category
        category_dir.mkdir(parents=True, exist_ok=True)
        for product, decision in rows:
            priority_counts[decision["priority"]] += 1
            used_urls.update(item["image_url"] for item in decision["mappings"] + decision["related"])
            (category_dir / f"{product['product_id']}.json").write_text(
                json.dumps(enriched(product, decision), ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"selected_total": sum(map(len, selected.values())),
              "selected_by_category": {category: len(selected[category]) for category in CATEGORIES},
              "selected_by_priority": dict(sorted(priority_counts.items())),
              "additional_candidates_attempted": dict(attempted),
              "excluded_products": {str(key): value for key, value in EXCLUDED_PRODUCTS.items()},
              "complete": all(len(selected[category]) == per_category for category in CATEGORIES)}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "image_checks.json").write_text(
        json.dumps({url: checks[url] for url in sorted(used_urls)}, ensure_ascii=False, indent=2), encoding="utf-8")
    with zipfile.ZipFile(output / "color_qualified_dataset_500.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(output / "report.json", "report.json")
        archive.write(output / "image_checks.json", "image_checks.json")
        for path in sorted((output / "data").rglob("*.json")):
            archive.write(path, "data/" + path.relative_to(output / "data").as_posix())
    return report


def run(args: argparse.Namespace) -> dict:
    args.work_dir.mkdir(parents=True, exist_ok=True)
    products = load_products(args.source_zip)
    sources = load_sources(products, args.evidence_dir, args.work_dir)
    checks = load_checks(args.evidence_dir, args.work_dir)
    page_limiter, api_limiter, image_limiter = RateLimit(args.page_interval), RateLimit(0.5), RateLimit(0.4)
    if args.recheck_current_images:
        recheck_current_images(args.output, checks, args.work_dir)
    for source in sources.values():
        ensure_checks(source, checks, image_limiter, args.work_dir)
    selected = defaultdict(list)
    selected_ids = set()
    for product in products:
        decision = classify(product, sources.get(product["product_id"], {}), checks)
        if decision:
            selected[product["dataset"]["logical_category"]].append((product, decision))
    for category in CATEGORIES:
        selected[category].sort(key=lambda item: (item[1]["priority"], item[0]["product_id"]))
        selected[category] = selected[category][:args.per_category]
        selected_ids.update(product["product_id"] for product, _ in selected[category])

    candidates = related_candidates(products, sources)
    attempted = Counter()
    for category in CATEGORIES:
        if len(selected[category]) >= args.per_category:
            continue
        for product_id in candidates.get(category, []):
            if len(selected[category]) >= args.per_category:
                break
            if product_id in selected_ids:
                continue
            attempted[category] += 1
            product, source = crawl_candidate(product_id, args.crawler_root, args.work_dir, page_limiter, api_limiter)
            if not product or not source or product.get("dataset", {}).get("logical_category") != category:
                continue
            ensure_checks(source, checks, image_limiter, args.work_dir)
            decision = classify(product, source, checks)
            if decision:
                selected[category].append((product, decision))
                selected_ids.add(product_id)
                print("accepted", category, len(selected[category]), "/", args.per_category, product_id, flush=True)
        if len(selected[category]) < args.per_category:
            print("shortfall", category, len(selected[category]), "/", args.per_category, flush=True)
    return write_output(args.output, selected, checks, attempted, args.per_category)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--crawler-root", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-category", type=int, default=100)
    parser.add_argument("--page-interval", type=float, default=2.2)
    parser.add_argument("--recheck-current-images", action="store_true")
    print(json.dumps(run(parser.parse_args()), ensure_ascii=False), flush=True)
