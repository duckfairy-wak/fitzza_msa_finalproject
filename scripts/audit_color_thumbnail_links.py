"""Collect source-backed color/product/image links from public product pages."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


NEXT_DATA = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/json,*/*"}
OPTION_SIZE_SUFFIX = re.compile(r"^(.+?)[\s/_-]+((?:[2-5]?X{0,3}[SML]|FREE|ONE\s*SIZE|OS|\d{2,3}(?:\.5)?))$", re.I)
DELIVERY_ANNOTATION = re.compile(
    r"\s*[\(\[\{][^()\[\]{}]*(?:예약|일반)\s*(?:발송|배송)[^()\[\]{}]*[\)\]\}]\s*"
    r"|\s*(?:\d{1,2}\s*[/.-]\s*\d{1,2}\s*)?(?:예약|일반)\s*(?:발송|배송)\s*",
    re.I,
)


class RateLimit:
    def __init__(self, interval: float):
        self.interval = interval
        self.lock = threading.Lock()
        self.next_request = 0.0

    def wait(self):
        with self.lock:
            delay = max(0.0, self.next_request - time.monotonic())
            if delay:
                time.sleep(delay)
            self.next_request = time.monotonic() + self.interval

    def defer(self, seconds: float):
        with self.lock:
            self.next_request = max(self.next_request, time.monotonic() + seconds)


def full_image_url(value):
    if not isinstance(value, str) or not value:
        return None
    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = "https://image.msscdn.net" + value
    parts = urllib.parse.urlparse(value)
    if parts.scheme not in {"https", "http"} or parts.hostname not in {"image.msscdn.net", "image.musinsa.com"}:
        return None
    if "/color_image/" in parts.path:
        return None
    return value


def normalize_color_option_label(value: object) -> str:
    label = re.sub(r"\s+", " ", str(value or "")).strip()
    label = DELIVERY_ANNOTATION.sub(" ", label)
    return re.sub(r"\s+", " ", label).strip(" -_/|,()[]{}")


def extract_option_links(options: dict, product_id: int) -> tuple[list[dict], list[dict]]:
    images, selected_colors = [], {}
    for group in options.get("basic", []):
        group_name = str(group.get("name") or "")
        is_color_group = any(word in group_name.lower() for word in ("컬러", "색상", "color", "colour"))
        is_size_group = any(word in group_name.lower() for word in ("사이즈", "size"))
        for value in group.get("optionValues", []):
            url = full_image_url(value.get("imageUrl"))
            if not url:
                continue
            label = str(value.get("name") or "")
            split = OPTION_SIZE_SUFFIX.fullmatch(label.strip())
            color = label if is_color_group and not is_size_group else None
            size = None
            if split and (is_color_group or is_size_group):
                color, size = split.groups()
            color = normalize_color_option_label(color) if color else None
            record = {
                "source_product_id": product_id, "image_product_id": product_id,
                "option_group": group_name, "option_label": label,
                "color_raw": color, "size_label": size, "image_url": url,
                "evidence": "Options.basic.optionValues.imageUrl", "scope": "source_option",
            }
            images.append(record)
            if color:
                rank = (2 if "예약" in label else 1 if "일반" in label else 0, label)
                previous = selected_colors.get(color)
                if previous is None or rank < previous[0]:
                    selected_colors[color] = (rank, record)
    return images, [value[1] for value in selected_colors.values()]


def extract_evidence(html: str, expected_id: int) -> dict:
    match = NEXT_DATA.search(html)
    if not match:
        raise ValueError("Page has no product __NEXT_DATA__")
    queries = json.loads(match.group(1))["props"]["pageProps"]["dehydratedState"]["queries"]
    detail, options, related = {}, {}, {}
    for query in queries:
        key = query.get("queryKey", [])
        data = query.get("state", {}).get("data") or {}
        data = data.get("data", data) if isinstance(data, dict) else {}
        if key == ["Detail", expected_id]:
            detail = data or {}
        elif key == ["Options", expected_id]:
            options = data or {}
        elif key == ["Detail", "OtherColorGoods", expected_id]:
            related = data or {}
    if detail.get("goodsNo") != expected_id:
        raise ValueError("Returned product ID does not match the requested product")

    mappings = []
    for tab in related.get("curationTabs", []):
        if tab.get("curationType") != "OTHER_COLOR":
            continue
        for item in tab.get("curationGoodsList", []):
            url = full_image_url(item.get("imageUrl"))
            raw_color = item.get("displayColorText")
            color = normalize_color_option_label(raw_color)
            if not url or not item.get("goodsNo") or not color:
                continue
            mappings.append({
                "source_product_id": expected_id,
                "image_product_id": item["goodsNo"],
                "color_raw": color,
                "color_source_raw": raw_color,
                "product_name": item.get("goodsName"),
                "image_url": url,
                "evidence": "OtherColorGoods.OTHER_COLOR",
                "scope": "source_product" if item["goodsNo"] == expected_id else "linked_product",
                "curation_id": tab.get("curationId"),
            })

    option_images, option_color_links = extract_option_links(options, expected_id)
    mappings.extend(option_color_links)

    urls = [full_image_url(detail.get("thumbnailImageUrl"))]
    urls.extend(full_image_url(row.get("imageUrl")) for row in detail.get("goodsImages", []))
    return {
        "product_id": expected_id,
        "status": "ok",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "name": detail.get("goodsNm"),
        "name_en": detail.get("goodsNmEng"),
        "style_no": detail.get("styleNo"),
        "product_image_urls": list(dict.fromkeys(url for url in urls if url)),
        "color_image_links": mappings,
        "option_image_links": option_images,
        "other_color_data": related,
        "option_data": options,
    }


def crawl_one(product: dict, output: Path, limiter: RateLimit, stop: threading.Event) -> dict:
    pid = product["product_id"]
    destination = output / "sources" / f"{pid}.json"
    if destination.exists():
        cached = json.loads(destination.read_text(encoding="utf-8"))
        if cached.get("status") == "ok" or cached.get("http_status") == 404:
            if cached.get("status") == "ok":
                images, links = extract_option_links(cached.get("option_data", {}), pid)
                cached["option_image_links"] = images
                cached["color_image_links"] = [row for row in cached.get("color_image_links", []) if row["scope"] != "source_option"] + links
                destination.write_text(json.dumps(cached, ensure_ascii=False, indent=2), encoding="utf-8")
            return cached
    if stop.is_set():
        return {"product_id": pid, "status": "not_attempted_after_access_limit"}
    result = None
    for attempt in range(3):
        try:
            limiter.wait()
            request = urllib.request.Request(f"https://www.musinsa.com/products/{pid}", headers=HEADERS)
            with urllib.request.urlopen(request, timeout=25) as response:
                result = extract_evidence(response.read().decode("utf-8"), pid)
                result["http_status"] = response.status
            break
        except urllib.error.HTTPError as exc:
            result = {"product_id": pid, "status": "http_error", "http_status": exc.code}
            if exc.code == 429 and attempt < 2:
                value = exc.headers.get("Retry-After", "90")
                delay = float(value) if value.isdigit() else 90.0
                result["retry_after"] = delay
                print("rate_limit", pid, "backoff_seconds", delay, flush=True)
                limiter.defer(max(delay, 60))
                continue
            if exc.code in (403, 429):
                stop.set()
            break
        except Exception as exc:
            result = {"product_id": pid, "status": "fetch_or_parse_error", "error": str(exc)[:300]}
            if attempt == 0:
                time.sleep(2)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def check_image(url: str, limiter: RateLimit) -> dict:
    limiter.wait()
    try:
        request = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(request, timeout=15) as response:
            mime = response.headers.get("Content-Type", "").split(";")[0]
            header = response.read(64)
            signature = header.startswith((b"\xff\xd8\xff", b"\x89PNG", b"GIF8")) or (header[:4] == b"RIFF" and header[8:12] == b"WEBP") or b"ftypavif" in header[:32]
            return {"method": "GET", "status": response.status, "content_type": mime, "image_signature": bool(signature), "reachable_image": bool(response.status == 200 and signature)}
    except urllib.error.HTTPError as exc:
        return {"method": "GET", "status": exc.code, "reachable_image": False,
                "error": str(exc)[:200]}
    except Exception as exc:
        return {"reachable_image": False, "error": str(exc)[:200]}


def package_results(output: Path, products: list[dict], results: list[dict], links: list[dict], report: dict):
    unique = {}
    for link in links:
        if not (link.get("image_check") or {}).get("reachable_image"):
            continue
        key = (link["image_product_id"], link["color_raw"], link["image_url"])
        record = unique.setdefault(key, {
            "product_id": link["image_product_id"], "color_raw": link["color_raw"],
            "image_url": link["image_url"], "evidence_page_ids": [], "evidence_types": [],
            "url_check": link["image_check"],
        })
        if link["source_product_id"] not in record["evidence_page_ids"]:
            record["evidence_page_ids"].append(link["source_product_id"])
        if link["evidence"] not in record["evidence_types"]:
            record["evidence_types"].append(link["evidence"])
    mappings = list(unique.values())
    (output / "verified_color_product_images.json").write_text(json.dumps(mappings, ensure_ascii=False, indent=2), encoding="utf-8")
    by_id = {row["product_id"]: row for row in results}
    for product in products:
        pid = product["product_id"]
        live = by_id.get(pid, {})
        own = [row for row in mappings if row["product_id"] == pid]
        related = [row for row in mappings if row["product_id"] != pid and pid in row["evidence_page_ids"]]
        enriched = {**product,
            "images": list(dict.fromkeys(product.get("images", []) + live.get("product_image_urls", []))),
            "color_image_mappings": own,
            "related_color_products": related,
            "image_mapping_audit": {
                "checked_at": report["checked_at"], "page_status": live.get("status"),
                "own_mapping_count": len(own), "related_mapping_count": len(related),
                "verification": "source_metadata_and_image_url_response",
                "all_color_options_covered": None,
            },
        }
        path = output / "enriched_data" / product["dataset"]["logical_category"] / f"{pid}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
    readme = f"""# 색상별 썸네일 수집 결과

원본 상품: {len(products)}개. 공개 상품 페이지 조회 결과: {report['page_status_counts']}.
원본 상품 중 자기 상품 ID에 연결된 색상명·이미지 URL 확보: {report['original_products_with_reachable_own_mapping']}개.
추가로 발견한 상품 ID: {report['additional_product_ids']}개.
응답과 이미지 시그니처를 확인한 색상 매핑 URL: {report['reachable_mapped_image_urls']}개.

## 파일

- data/: 원본 상품 {len(products)}개에 색상 이미지 연결을 추가한 JSON. 기존 상품 ID·실측은 유지합니다.
- verified_color_product_images.json: 실제 사이트 상품 ID, 사이트 색상명, 이미지 URL, 근거 페이지 ID.
- report.json: 500개 분모를 유지한 수집·매핑·이미지 검증 통계.
- sources/: 사이트 OtherColorGoods와 Options의 원본 공개 데이터.

## 필드

color_image_mappings는 해당 상품 ID 자체의 색상과 사진 연결입니다.
related_color_products는 사이트가 다른 색상으로 연결한 별도 상품 ID의 사진입니다. 이 상품들은 원본 500개에 추가된 완전한 상품 데이터가 아니며, 원본 상품의 실측을 이들에 복사하지 않았습니다.
같은 상품 안의 색상 옵션은 같은 상품 ID를 유지합니다. 별도 상품 ID는 사이트에서 실제로 제공한 ID만 사용합니다.
이미지 GET 응답, Content-Type, 파일 시그니처를 확인했습니다. 500개 전체 사진의 육안 판정이나 각 상품의 모든 색상 옵션 커버리지를 의미하지 않습니다.
사이트가 제공한 색상명을 그대로 유지하므로 복합 색상·축약 표기가 포함될 수 있습니다. 일반 색상 아이콘은 제외했습니다.
현재 Fashion-CLIP 인덱서는 신규 필드를 읽도록 담당자 수정이 필요합니다. 이번 작업은 Qdrant에 적재하지 않았습니다.
"""
    (output / "README.md").write_text(readme, encoding="utf-8")
    with zipfile.ZipFile(output / "color_image_dataset.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((output / "enriched_data").rglob("*.json")):
            archive.write(path, "data/" + path.relative_to(output / "enriched_data").as_posix())
        for name in ("README.md", "report.json", "verified_color_product_images.json", "image_checks.json"):
            archive.write(output / name, name)
        for path in sorted((output / "sources").glob("*.json")):
            archive.write(path, "sources/" + path.name)


def run(args):
    output = args.output
    (output / "sources").mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.source_zip) as archive:
        products = [json.loads(archive.read(name)) for name in sorted(archive.namelist()) if name.endswith(".json")]
    if args.limit:
        products = products[:args.limit]
    limiter, stop = RateLimit(args.page_interval), threading.Event()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        futures = [pool.submit(crawl_one, product, output, limiter, stop) for product in products]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            if len(results) % 25 == 0:
                print("pages", len(results), "/", len(products), dict(Counter(x["status"] for x in results)), flush=True)
    results.sort(key=lambda row: row["product_id"])
    links = [link for row in results for link in row.get("color_image_links", [])]
    urls = sorted({row["image_url"] for row in links})
    checks_path = output / "image_checks.json"
    checks = json.loads(checks_path.read_text(encoding="utf-8")) if checks_path.exists() else {}
    for check in checks.values():
        if check.get("method") == "GET" and check.get("status") == 200 and check.get("image_signature"):
            check["reachable_image"] = True
    pending = [url for url in urls if url not in checks or checks[url].get("method") != "GET" or not checks[url].get("reachable_image")]
    print("image_urls_to_check", len(pending), flush=True)
    image_limiter = RateLimit(0.4)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(check_image, url, image_limiter): url for url in pending}
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            checks[futures[future]] = future.result()
            if index % 100 == 0:
                print("images", index, "/", len(pending), flush=True)
                checks_path.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    checks_path.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    for link in links:
        link["image_check"] = checks.get(link["image_url"])
    source_ids = {row["product_id"] for row in products}
    old_urls = {url for row in products for url in row.get("images", [])}
    gallery_urls = {url for row in results for url in row.get("product_image_urls", [])}
    valid_links = [row for row in links if (row.get("image_check") or {}).get("reachable_image")]
    option_coverage = []
    for result in results:
        expected = set()
        for group in result.get("option_data", {}).get("basic", []):
            group_name = str(group.get("name") or "").lower()
            is_color = any(term in group_name for term in ("컬러", "색상", "color", "colour"))
            is_size = any(term in group_name for term in ("사이즈", "size"))
            for value in group.get("optionValues", []):
                label = str(value.get("name") or "")
                split = OPTION_SIZE_SUFFIX.fullmatch(label.strip())
                if split and (is_color or is_size):
                    expected.add(split.group(1))
                elif is_color and not is_size and label:
                    expected.add(label)
        if expected:
            covered = {row["color_raw"] for row in valid_links if row["source_product_id"] == result["product_id"] and row["scope"] == "source_option"}
            option_coverage.append({"product_id": result["product_id"], "declared_color_labels": sorted(expected), "mapped_color_labels": sorted(expected & covered), "missing_color_labels": sorted(expected - covered)})
    report = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "input_product_count": len(products),
        "page_status_counts": dict(Counter(row["status"] for row in results)),
        "sources_with_explicit_color_image_links": len({row["source_product_id"] for row in links}),
        "sources_with_reachable_explicit_links": len({row["source_product_id"] for row in valid_links}),
        "sources_with_own_color_thumbnail": len({row["source_product_id"] for row in valid_links if row["scope"] == "source_product"}),
        "sources_with_color_option_images": len({row["source_product_id"] for row in valid_links if row["scope"] == "source_option"}),
        "original_products_with_reachable_own_mapping": len({row["image_product_id"] for row in valid_links} & source_ids),
        "original_product_ids_without_reachable_own_mapping": sorted(source_ids - {row["image_product_id"] for row in valid_links}),
        "color_link_records": len(links),
        "unique_mapped_image_urls": len(urls),
        "reachable_mapped_image_urls": sum(checks[url].get("reachable_image", False) for url in urls),
        "unique_linked_product_ids": len({row["image_product_id"] for row in links}),
        "additional_product_ids": len({row["image_product_id"] for row in links} - source_ids),
        "new_mapped_image_urls": len(set(urls) - old_urls),
        "new_reachable_mapped_image_urls": len({row["image_url"] for row in valid_links} - old_urls),
        "unassigned_product_image_urls": len(gallery_urls),
        "new_unassigned_product_image_urls": len(gallery_urls - old_urls),
        "products_with_recognized_color_options": len(option_coverage),
        "products_with_all_recognized_color_option_images": sum(not row["missing_color_labels"] for row in option_coverage),
        "color_option_coverage": option_coverage,
        "per_product": [{
            "product_id": row["product_id"], "status": row["status"],
            "explicit_link_count": len(row.get("color_image_links", [])),
            "own_link_count": sum(link["scope"] == "source_product" for link in row.get("color_image_links", [])),
        } for row in results],
    }
    (output / "color_image_links.json").write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    package_results(output, products, results, links, report)
    print(json.dumps({key: value for key, value in report.items() if key not in {"per_product", "original_product_ids_without_reachable_own_mapping", "color_option_coverage"}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--page-interval", type=float, default=2.2)
    run(parser.parse_args())
