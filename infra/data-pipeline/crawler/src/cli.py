from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from src import __version__
from src.collector import cleanup_metadata, select_balanced
from src.collector.color_product_export import export_dataset
from src.collector.config import CATEGORY_CONFIG
from src.collector.discover_targeted import run as run_discover
from src.collector.hydrate_selected import run as run_hydrate
from src.collector.rules import has_required_size
from src.collector.screen_until_ready import run as run_screen


PROGRAM_NAME = "fashion-crawler"
SEASONS = ["봄", "여름", "가을", "겨울"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"python -m src.cli",
        description="무신사 균형 데이터셋 수집 통합 CLI",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"{PROGRAM_NAME} {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    discover = subparsers.add_parser(
        "discover",
        help="목표량 기반으로 카테고리별 후보를 확보",
    )
    discover.add_argument("--factor", type=float, default=1.6)
    discover.add_argument("--min-candidates", type=int, default=0)
    discover.add_argument(
        "--category",
        choices=list(CATEGORY_CONFIG),
        default=None,
    )
    discover.add_argument("--page-size", type=int, default=60)
    discover.add_argument("--max-pages-per-sort", type=int, default=40)

    screen = subparsers.add_parser(
        "screen",
        help="후보를 검증하고 quota 충족 시 자동 중단",
    )
    screen.add_argument(
        "--category",
        choices=list(CATEGORY_CONFIG),
        default=None,
    )
    screen.add_argument("--chunk-size", type=int, default=100)
    screen.add_argument("--delay", type=float, default=0.8)
    screen.add_argument("--headful", action="store_true")
    screen.add_argument("--max-new", type=int, default=0)

    subparsers.add_parser(
        "select",
        help="max-flow로 카테고리별 사계절 균형 selection 생성",
    )

    hydrate = subparsers.add_parser(
        "hydrate",
        help="선정 상품에 actual-size를 붙여 최종 저장",
    )
    hydrate.add_argument(
        "--category",
        choices=list(CATEGORY_CONFIG),
        required=True,
    )
    hydrate.add_argument("--limit", type=int, default=20)
    hydrate.add_argument("--delay", type=float, default=0.8)

    subparsers.add_parser(
        "cleanup",
        help="기존 JSON의 비정상 시즌 연도를 정규화",
    )

    export_colors = subparsers.add_parser(
        "export-colors",
        help="색상별 상품 후보를 별도 디렉터리로 내보내고 미확정 항목을 기록",
    )
    export_colors.add_argument(
        "--source",
        type=Path,
        default=Path("data/final_products"),
    )
    export_colors.add_argument(
        "--output",
        type=Path,
        default=Path("data/color_products"),
    )

    status = subparsers.add_parser(
        "status",
        help="후보, screening, selection, hydration 진행률 조회",
    )
    status.add_argument(
        "--category",
        choices=list(CATEGORY_CONFIG),
        default=None,
    )
    status.add_argument("--json", action="store_true", dest="as_json")

    return parser


def _hydrated_count(category: str, selected_ids: set[int]) -> int:
    path = Path("data/final_products") / category
    if not path.exists():
        return 0

    count = 0
    for item in path.glob("*.json"):
        try:
            product_id = int(item.stem)
            product = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            continue

        if product_id in selected_ids and has_required_size(product, category):
            count += 1

    return count


def _candidate_count(category: str) -> int:
    path = Path("data/candidates") / f"{category}.json"
    if not path.exists():
        return 0

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0

    return len(value) if isinstance(value, list) else 0


def collect_status(category: str) -> dict[str, Any]:
    selection = select_balanced.select_category(category)
    selected_ids = {
        int(item["product_id"])
        for item in selection["items"]
    }
    return {
        "category": category,
        "candidates": _candidate_count(category),
        "screened_usable": selection["screened_usable"],
        "selected": selection["selected"],
        "target": selection["required"],
        "counts": selection["counts"],
        "deficit": selection["deficit"],
        "complete": selection["complete"],
        "hydrated": _hydrated_count(category, selected_ids),
    }


def print_status(category: str | None = None, *, as_json: bool = False) -> None:
    categories = [category] if category else list(CATEGORY_CONFIG)
    rows = [collect_status(item) for item in categories]

    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    print(
        f"{'카테고리':<6} {'후보':>6} {'usable':>7} "
        f"{'selected':>12} {'hydrated':>9} {'complete':>9}"
    )
    print("-" * 62)

    for row in rows:
        print(
            f"{row['category']:<6} {row['candidates']:>6} "
            f"{row['screened_usable']:>7} "
            f"{row['selected']:>5}/{row['target']:<6} "
            f"{row['hydrated']:>9} {str(row['complete']):>9}"
        )
        counts = ", ".join(
            f"{season} {row['counts'][season]}" for season in SEASONS
        )
        print(f"  counts : {counts}")
        if row["deficit"] is None:
            print("  deficit: not enforced for this category")
        else:
            deficit = ", ".join(
                f"{season} {row['deficit'][season]}" for season in SEASONS
            )
            print(f"  deficit: {deficit}")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.command == "discover":
        asyncio.run(run_discover(args))
    elif args.command == "screen":
        asyncio.run(run_screen(args))
    elif args.command == "select":
        select_balanced.main()
    elif args.command == "hydrate":
        asyncio.run(run_hydrate(args))
    elif args.command == "cleanup":
        cleanup_metadata.main()
    elif args.command == "export-colors":
        print(json.dumps(export_dataset(args.source, args.output), ensure_ascii=False, indent=2))
    elif args.command == "status":
        print_status(args.category, as_json=args.as_json)


if __name__ == "__main__":
    main()
