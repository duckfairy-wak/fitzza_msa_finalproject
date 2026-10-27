"""Concurrent screening without browser rendering for cloud batch collection."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.collector.config import CATEGORY_CONFIG
from src.collector.rules import (
    ACCESSORY_FALLBACK_CATEGORIES,
    has_actual_size,
    is_allowed_gender,
    is_target_category,
)
from src.collector.screen_until_ready import handled_ids, read_candidates
from src.collector.select_balanced import select_category
from src.musinsa_parser import normalize_musinsa_product
from src.musinsa_size import normalize_accessory_option_size, normalize_actual_size


HEADERS = {
    "Accept": "text/html,application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/154 Safari/537.36"
    ),
}

REQUEST_INTERVAL_SECONDS = 0.4
_RATE_CONDITION = threading.Condition()
_NEXT_REQUEST_AT = 0.0
_BLOCKED_UNTIL = 0.0


def wait_for_request_slot() -> None:
    global _NEXT_REQUEST_AT
    while True:
        with _RATE_CONDITION:
            now = time.monotonic()
            ready_at = max(_NEXT_REQUEST_AT, _BLOCKED_UNTIL)
            if ready_at <= now:
                _NEXT_REQUEST_AT = now + REQUEST_INTERVAL_SECONDS
                return
            delay = min(ready_at - now, 1.0)
        time.sleep(delay)


def apply_global_cooldown(seconds: float) -> None:
    global _BLOCKED_UNTIL
    with _RATE_CONDITION:
        _BLOCKED_UNTIL = max(_BLOCKED_UNTIL, time.monotonic() + seconds)
        _RATE_CONDITION.notify_all()


def retry_after_seconds(error: HTTPError, attempt: int) -> float:
    value = error.headers.get("Retry-After")
    try:
        return max(float(value), 1.0)
    except (TypeError, ValueError):
        return float(2 ** attempt)


def fetch_bytes(url: str, referer: str, attempts: int = 4) -> bytes:
    request = Request(url, headers={**HEADERS, "Referer": referer})
    last_error = "unknown"
    for attempt in range(attempts):
        wait_for_request_slot()
        try:
            with urlopen(request, timeout=30) as response:
                if response.status >= 400:
                    raise RuntimeError(f"HTTP {response.status}: {url}")
                return response.read()
        except HTTPError as error:
            last_error = f"HTTP {error.code}"
            if error.code == 429:
                cooldown = retry_after_seconds(error, attempt) + random.uniform(0.5, 1.5)
                apply_global_cooldown(cooldown)
                print(f"  rate-limit cooldown={cooldown:.1f}s", flush=True)
                continue
            if not 500 <= error.code < 600:
                raise
        except (URLError, TimeoutError) as error:
            last_error = f"{type(error).__name__}: {error}"
        if attempt + 1 == attempts:
            raise RuntimeError(f"request exhausted retries ({last_error}): {url}")
        time.sleep(2 ** attempt + random.uniform(0, 0.25))
    raise RuntimeError(f"request exhausted retries ({last_error}): {url}")


def fetch_product(product_id: int, category: str) -> dict:
    product_url = f"https://www.musinsa.com/products/{product_id}"
    size_url = f"https://goods-detail.musinsa.com/api2/goods/{product_id}/actual-size"
    size_payload = json.loads(fetch_bytes(size_url, product_url))
    actual_size = normalize_actual_size(
        size_payload.get("data") if isinstance(size_payload, dict) else None
    )
    if (category not in ACCESSORY_FALLBACK_CATEGORIES
            and not has_actual_size({"size": actual_size})):
        return {"product_id": product_id, "_rejection": "actual_size_unavailable",
                "size": actual_size}
    html = fetch_bytes(product_url, product_url).decode("utf-8")
    product = normalize_musinsa_product(html, product_url)
    if int(product["product_id"]) != product_id:
        raise ValueError("requested product identity mismatch")
    product["size"] = (
        actual_size
        if has_actual_size({"size": actual_size})
        else normalize_accessory_option_size(product)
    )
    if not product["size"]["available"]:
        product["_rejection"] = "size_option_unavailable"
    return product


def save_result(category: str, product_id: int, product: dict) -> str:
    screened = Path("data/screened") / category
    rejected = Path("data/screened_rejected") / category
    failed = Path("data/screened_failed") / category
    for path in (screened, rejected, failed):
        path.mkdir(parents=True, exist_ok=True)
    reason = product.pop("_rejection", None)
    if reason is None and not is_allowed_gender(product):
        reason = "gender_not_allowed"
    if reason is None and not is_target_category(product, category):
        reason = "category_mismatch"
    if reason is None and not product.get("color_image_mappings"):
        reason = "color_image_mappings_missing"
    if reason:
        output = {"product_id": product_id, "reason": reason}
        (rejected / f"{product_id}.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return f"REJECT {reason}"
    (screened / f"{product_id}.json").write_text(
        json.dumps(product, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    rejection = rejected / f"{product_id}.json"
    if rejection.exists():
        rejection.unlink()
    failure = failed / f"{product_id}.json"
    if failure.exists():
        failure.unlink()
    return f"OK gender={product.get('gender', {}).get('normalized')}"


async def process_candidate(semaphore: asyncio.Semaphore, category: str,
                            product_id: int) -> tuple[int, bool]:
    async with semaphore:
        try:
            product = await asyncio.to_thread(fetch_product, product_id, category)
            outcome = save_result(category, product_id, product)
            print(f"  screen {product_id} ... {outcome}", flush=True)
            return product_id, True
        except Exception as error:
            failed = Path("data/screened_failed") / category
            failed.mkdir(parents=True, exist_ok=True)
            (failed / f"{product_id}.json").write_text(json.dumps({
                "product_id": product_id, "reason": "crawl_failed",
                "detail": str(error)}, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  screen {product_id} ... FAILED {type(error).__name__}", flush=True)
            return product_id, False


async def run(category: str, max_new: int, workers: int) -> None:
    candidates = read_candidates(category)
    done = handled_ids(category)
    pending = [int(item["product_id"]) for item in candidates
               if int(item["product_id"]) not in done][:max_new]
    selection = select_category(category)
    print(f"[{category}] selected={selection['selected']}/{selection['required']} "
          f"pending_batch={len(pending)} workers={workers}", flush=True)
    if selection["complete"] or not pending:
        return
    semaphore = asyncio.Semaphore(workers)
    results = await asyncio.gather(*(
        process_candidate(semaphore, category, product_id) for product_id in pending
    ))
    completed = sum(success for _, success in results)
    selection = select_category(category)
    print(f"[{category}] handled={completed}/{len(pending)} "
          f"selected={selection['selected']}/{selection['required']} "
          f"complete={selection['complete']}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--category", choices=list(CATEGORY_CONFIG), required=True)
    parser.add_argument("--max-new", type=int, default=200)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.max_new <= 1000 or not 1 <= args.workers <= 16:
        raise ValueError("invalid batch or worker count")
    asyncio.run(run(args.category, args.max_new, args.workers))


if __name__ == "__main__":
    main()
