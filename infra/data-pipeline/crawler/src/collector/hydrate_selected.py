from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from src.collector.config import CATEGORY_CONFIG
from src.collector.rules import has_required_size


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="선정된 상품에 actual-size를 붙여 최종 dataset 저장"
    )
    parser.add_argument(
        "--category",
        choices=list(CATEGORY_CONFIG.keys()),
        required=True,
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--delay", type=float, default=0.8)
    return parser.parse_args()


async def run(args: argparse.Namespace | None = None) -> None:
    args = args or parse_args()

    selection_path = Path("data/selection") / f"{args.category}.json"
    if not selection_path.exists():
        raise FileNotFoundError(selection_path)

    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    items = selection.get("items", [])

    output_dir = Path("data/final_products") / args.category
    screened_dir = Path("data/screened") / args.category
    output_dir.mkdir(parents=True, exist_ok=True)

    saved = 0

    for item in items:
        if saved >= args.limit:
            break

        product_id = int(item["product_id"])
        output_path = output_dir / f"{product_id}.json"

        if output_path.exists():
            try:
                existing = json.loads(output_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            if has_required_size(existing, args.category):
                continue

        screened_path = screened_dir / f"{product_id}.json"
        if not screened_path.exists():
            continue

        product = json.loads(screened_path.read_text(encoding="utf-8"))
        if not has_required_size(product, args.category):
            print(f"SKIP {product_id}: required size unavailable")
            continue

        product.setdefault("season", {})
        product["season"]["primary"] = item["primary_season"]
        product["season"]["primary_source"] = item["primary_source"]
        product["season"]["primary_candidates"] = item[
            "primary_candidates"
        ]

        product["dataset"] = {
            "logical_category": args.category,
            "primary_season": item["primary_season"],
            "gender_scope": "MALE_AND_UNISEX",
        }

        output_path.write_text(
            json.dumps(product, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        saved += 1
        print(
            f"[{saved}/{args.limit}] {product_id} "
            f"season={item['primary_season']} SAVED"
        )

    print(f"\nnewly hydrated: {saved}")


if __name__ == "__main__":
    asyncio.run(run())
