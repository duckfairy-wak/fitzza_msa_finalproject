from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from src.collector.candidate_fetcher import fetch_candidate_page
from src.collector.config import CATEGORY_CONFIG, DISCOVERY_SORT_CODES


def read_seed_ids() -> set[int]:
    manifest_path = os.environ.get("SEED_MANIFEST")
    if not manifest_path:
        return set()
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    identifiers = [int(product["product_id"]) for product in manifest["products"]]
    if not identifiers or len(identifiers) != len(set(identifiers)):
        raise ValueError("Seed manifest must contain unique product IDs")
    return set(identifiers)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="카테고리 목표량 기반 무신사 후보 풀 확대"
    )
    parser.add_argument(
        "--factor",
        type=float,
        default=1.6,
        help="최종 목표 대비 후보 oversampling 배수 (기본 1.6)",
    )
    parser.add_argument(
        "--min-candidates",
        type=int,
        default=0,
        help="카테고리별 최소 후보 수 (기본 0)",
    )
    parser.add_argument(
        "--category",
        choices=list(CATEGORY_CONFIG.keys()),
        default=None,
        help="특정 카테고리만 후보 풀 확대",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=60,
        help="목록 API 페이지 크기 (기본 60)",
    )
    parser.add_argument(
        "--max-pages-per-sort",
        type=int,
        default=40,
        help="정렬별 최대 페이지 수",
    )
    return parser.parse_args()


def merge_candidates(
    destination: dict[int, dict[str, Any]],
    candidates: list[dict[str, Any]],
    *,
    category: str,
    sort_code: str,
    page: int,
) -> int:
    before = len(destination)

    for item in candidates:
        product_id = int(item["product_id"])

        if product_id not in destination:
            destination[product_id] = {
                **item,
                "source_category": category,
                "discovered_by": [],
            }

        marker = {"sort": sort_code, "page": page}
        if marker not in destination[product_id]["discovered_by"]:
            destination[product_id]["discovered_by"].append(marker)

    return len(destination) - before


async def run(args: argparse.Namespace | None = None) -> None:
    args = args or parse_args()

    if args.factor < 1.0:
        raise ValueError("--factor는 1.0 이상이어야 합니다.")
    if args.min_candidates < 0:
        raise ValueError("--min-candidates는 0 이상이어야 합니다.")
    if not 1 <= args.page_size <= 60:
        raise ValueError("--page-size는 1~60 범위로 사용하세요.")

    output_dir = Path("data/candidates")
    output_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "factor": args.factor,
        "min_candidates": args.min_candidates,
        "page_size": args.page_size,
        "sort_codes": DISCOVERY_SORT_CODES,
        "categories": {},
    }
    seed_ids = read_seed_ids()
    summary["excluded_seed_count"] = len(seed_ids)

    async with async_playwright() as p:
        request = await p.request.new_context(
            extra_http_headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/154 Safari/537.36"
                )
            }
        )

        try:
            categories = (
                [args.category]
                if args.category
                else list(CATEGORY_CONFIG.keys())
            )

            for category in categories:
                config = CATEGORY_CONFIG[category]
                target = config["total_quota"]
                candidate_target = max(
                    math.ceil(target * args.factor),
                    args.min_candidates,
                )
                category_code = config["source_category"]

                path = output_dir / f"{category}.json"

                collected: dict[int, dict[str, Any]] = {}

                # 기존 후보 파일이 있으면 이어서 확장
                if path.exists():
                    existing = json.loads(path.read_text(encoding="utf-8"))
                    for item in existing:
                        if int(item["product_id"]) not in seed_ids:
                            collected[int(item["product_id"])] = item

                print(
                    f"\n[{category}] final target={target}, "
                    f"candidate target={candidate_target}, "
                    f"existing={len(collected)}"
                )

                page_by_sort = {sort_code: 1 for sort_code in DISCOVERY_SORT_CODES}
                exhausted_sorts: set[str] = set()
                while (
                    len(collected) < candidate_target
                    and len(exhausted_sorts) < len(DISCOVERY_SORT_CODES)
                ):
                    for sort_code in DISCOVERY_SORT_CODES:
                        if sort_code in exhausted_sorts:
                            continue

                        page = page_by_sort[sort_code]

                        if page > args.max_pages_per_sort:
                            exhausted_sorts.add(sort_code)
                            continue

                        print(
                            f"  {sort_code} page={page} ... ",
                            end="",
                            flush=True,
                        )

                        items = await fetch_candidate_page(
                            request,
                            category_code=category_code,
                            page=page,
                            page_size=args.page_size,
                            sort_code=sort_code,
                        )

                        added = merge_candidates(
                            collected,
                            [item for item in items if int(item["product_id"]) not in seed_ids],
                            category=category,
                            sort_code=sort_code,
                            page=page,
                        )
                        page_by_sort[sort_code] += 1

                        print(
                            f"fetched={len(items)}, new={added}, "
                            f"unique={len(collected)}/{candidate_target}"
                        )

                        if len(items) == 0:
                            exhausted_sorts.add(sort_code)

                        if len(collected) >= candidate_target:
                            break

                result = list(collected.values())
                # 최근 상품이 색상 이미지와 실측 데이터를 보유할 가능성이 높다.
                # screening은 파일 순서를 따르므로 최신 ID를 먼저 검증한다.
                result.sort(key=lambda x: x["product_id"], reverse=True)

                path.write_text(
                    json.dumps(result, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

                summary["categories"][category] = {
                    "source_category": category_code,
                    "final_target": target,
                    "candidate_target": candidate_target,
                    "unique_candidates": len(result),
                    "enough_candidates": len(result) >= target,
                    "output": str(path),
                }

        finally:
            await request.dispose()

    summary_path = output_dir / "summary_targeted.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n=== targeted discovery complete ===")
    for category, info in summary["categories"].items():
        print(
            f"{category:4}: "
            f"{info['unique_candidates']:4} candidates / "
            f"final {info['final_target']}"
        )


if __name__ == "__main__":
    asyncio.run(run())
