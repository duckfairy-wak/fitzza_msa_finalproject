from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

from src.collector.batch_crawler import BatchProductCrawler
from src.collector.config import CATEGORY_CONFIG
from src.collector.rules import (
    ACCESSORY_FALLBACK_CATEGORIES,
    has_actual_size,
    has_required_size,
    is_allowed_gender,
    is_target_category,
)
from src.collector.select_balanced import select_category
from src.musinsa_size import normalize_accessory_option_size


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="후보를 단계적으로 screening하면서 계절 quota가 충족되면 자동 중단"
    )
    parser.add_argument(
        "--category",
        choices=list(CATEGORY_CONFIG.keys()),
        default=None,
        help="특정 카테고리만 처리. 생략하면 전체 카테고리 순회",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=100,
        help="quota 재계산 전 한 번에 새로 screen할 후보 수",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.8,
        help="상품 상세 요청 사이 대기 시간(초)",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="브라우저 화면 표시",
    )
    parser.add_argument(
        "--max-new",
        type=int,
        default=0,
        help="이번 실행에서 새로 screen할 전체 최대 개수. 0이면 제한 없음",
    )
    return parser.parse_args()


def read_candidates(category: str) -> list[dict]:
    path = Path("data/candidates") / f"{category}.json"
    if not path.exists():
        raise FileNotFoundError(path)

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"후보 파일 형식 오류: {path}")

    return data


def handled_ids(category: str) -> set[int]:
    ids: set[int] = set()

    screened_dir = Path("data/screened") / category
    if screened_dir.exists():
        for path in screened_dir.glob("*.json"):
            try:
                product = json.loads(path.read_text(encoding="utf-8"))
                if has_required_size(product, category):
                    ids.add(int(path.stem))
            except (OSError, ValueError, json.JSONDecodeError):
                pass

    rejected_dir = Path("data/screened_rejected") / category
    if rejected_dir.exists():
        for path in rejected_dir.glob("*.json"):
            try:
                if category in ACCESSORY_FALLBACK_CATEGORIES:
                    rejected = json.loads(path.read_text(encoding="utf-8"))
                    if rejected.get("reason") in {
                        "actual_size_unavailable",
                        "color_image_mappings_missing",
                    }:
                        continue
                ids.add(int(path.stem))
            except (OSError, ValueError, json.JSONDecodeError):
                pass

    return ids


def print_status(category: str) -> dict:
    result = select_category(category)

    print(
        f"\n[{category}] "
        f"usable={result['screened_usable']} "
        f"selected={result['selected']}/{result['required']} "
        f"complete={result['complete']}"
    )
    print(f"  counts : {result['counts']}")
    print(
        f"  deficit: {result['deficit']}"
        if result["season_balance_required"]
        else "  deficit: not enforced for this category"
    )

    return result


async def screen_category(
    crawler: BatchProductCrawler,
    category: str,
    *,
    chunk_size: int,
    max_new_remaining: int | None,
) -> tuple[int, bool]:
    candidates = read_candidates(category)

    screened_dir = Path("data/screened") / category
    rejected_dir = Path("data/screened_rejected") / category
    failed_dir = Path("data/screened_failed") / category

    screened_dir.mkdir(parents=True, exist_ok=True)
    rejected_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    result = print_status(category)
    if result["complete"]:
        return 0, True

    done = handled_ids(category)
    new_total = 0

    while not result["complete"]:
        processed_this_chunk = 0

        for candidate in candidates:
            if processed_this_chunk >= chunk_size:
                break

            if max_new_remaining is not None and new_total >= max_new_remaining:
                return new_total, False

            product_id = int(candidate["product_id"])

            if product_id in done:
                continue

            print(
                f"  screen {product_id} ... ",
                end="",
                flush=True,
            )

            try:
                actual_size = await crawler.fetch_actual_size(
                    product_id,
                    strict=True,
                )

                if (category not in ACCESSORY_FALLBACK_CATEGORIES
                        and not has_actual_size({"size": actual_size})):
                    out = {
                        "product_id": product_id,
                        "reason": "actual_size_unavailable",
                        "size": actual_size,
                    }
                    (rejected_dir / f"{product_id}.json").write_text(
                        json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print("REJECT actual-size")
                    done.add(product_id)
                    processed_this_chunk += 1
                    new_total += 1
                    continue

                product = await crawler.fetch_basic_product(product_id)
                product["size"] = (
                    actual_size
                    if has_actual_size({"size": actual_size})
                    else normalize_accessory_option_size(product)
                )

                if not has_required_size(product, category):
                    out = {
                        "product_id": product_id,
                        "reason": "size_option_unavailable",
                        "size": product["size"],
                    }
                    (rejected_dir / f"{product_id}.json").write_text(
                        json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print("REJECT size-option")
                    done.add(product_id)
                    processed_this_chunk += 1
                    new_total += 1
                    continue

                if not is_allowed_gender(product):
                    out = {
                        "product_id": product_id,
                        "reason": "gender_not_allowed",
                        "gender": product.get("gender"),
                    }
                    (rejected_dir / f"{product_id}.json").write_text(
                        json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print("REJECT gender")

                elif not is_target_category(product, category):
                    out = {
                        "product_id": product_id,
                        "reason": "category_mismatch",
                        "category": product.get("category"),
                    }
                    (rejected_dir / f"{product_id}.json").write_text(
                        json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print("REJECT category")

                elif not product.get("color_image_mappings"):
                    out = {
                        "product_id": product_id,
                        "reason": "color_image_mappings_missing",
                    }
                    (rejected_dir / f"{product_id}.json").write_text(
                        json.dumps(out, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print("REJECT color-image")

                else:
                    product = await crawler.attach_essential_material(product)
                    (screened_dir / f"{product_id}.json").write_text(
                        json.dumps(product, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

                    # 이전 transient failure가 있었다면 성공 시 제거
                    failed_path = failed_dir / f"{product_id}.json"
                    if failed_path.exists():
                        failed_path.unlink()

                    print(
                        "OK "
                        f"gender={product.get('gender', {}).get('normalized')} "
                        f"season={product.get('season', {}).get('original', [])} "
                        f"collection="
                        f"{product.get('season', {}).get('collection', {}).get('type')}"
                    )

            except Exception as exc:
                out = {
                    "product_id": product_id,
                    "reason": "crawl_failed",
                    "detail": str(exc),
                }
                (failed_dir / f"{product_id}.json").write_text(
                    json.dumps(out, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(f"FAILED {type(exc).__name__}")

            done.add(product_id)
            processed_this_chunk += 1
            new_total += 1

        result = print_status(category)

        if result["complete"]:
            return new_total, True

        if processed_this_chunk == 0:
            print(f"[{category}] 더 이상 처리할 후보가 없습니다.")
            return new_total, False

    return new_total, True


async def run(args: argparse.Namespace | None = None) -> None:
    args = args or parse_args()

    categories = (
        [args.category]
        if args.category
        else list(CATEGORY_CONFIG.keys())
    )

    max_new = args.max_new if args.max_new > 0 else None
    total_new = 0

    async with async_playwright() as p:
        crawler = BatchProductCrawler(
            p,
            headless=not args.headful,
            delay_seconds=max(args.delay, 0.3),
        )
        await crawler.start()

        try:
            for category in categories:
                remaining = (
                    None
                    if max_new is None
                    else max(0, max_new - total_new)
                )

                if remaining == 0:
                    break

                added, complete = await screen_category(
                    crawler,
                    category,
                    chunk_size=args.chunk_size,
                    max_new_remaining=remaining,
                )
                total_new += added

                print(
                    f"\n[{category}] "
                    f"이번 실행 신규 screening={added}, "
                    f"quota_complete={complete}"
                )

        finally:
            await crawler.close()

    print(f"\n총 신규 screening: {total_new}")
    print(
        "다음 단계: python -m src.collector.select_balanced"
    )


if __name__ == "__main__":
    asyncio.run(run())
