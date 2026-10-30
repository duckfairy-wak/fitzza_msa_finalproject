"""Qdrant 컬렉션에서 실제 판매 옵션(option_items)에 존재하지 않는 색상 포인트를 검출 및 삭제하는 스크립트.

사용법:
    # 1. 삭제 대상 미리보기 (Dry-run)
    python scripts/purge_unsellable_qdrant_points.py --dry-run

    # 2. 실제 삭제 실행
    python scripts/purge_unsellable_qdrant_points.py [--qdrant-url http://localhost:6333] [--collection musinsa_products]
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path("product-service/src/main/resources/final_products")
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_COLLECTION = "musinsa_products"


def extract_sellable_colors(product: dict) -> set[str]:
    """Extract active/sellable color names (lowercase) from option_items."""
    option_items = product.get("option_items") or []
    if not option_items:
        return set()

    options = product.get("options") or []
    color_group_idx = None
    for idx, opt in enumerate(options):
        name = opt.get("name") or ""
        if any(kw in name.lower() for kw in ["컬러", "색상", "color"]):
            color_group_idx = idx
            break

    sellable = set()
    for item in option_items:
        if item.get("activated") is False:
            continue
        values = item.get("values") or []
        if not values:
            continue
        if color_group_idx is not None and color_group_idx < len(values):
            val = values[color_group_idx]
            if isinstance(val, str) and val.strip():
                sellable.add(val.strip().lower())
        else:
            for val in values:
                if isinstance(val, str) and val.strip():
                    sellable.add(val.strip().lower())
    return sellable


def build_sellable_colors_map(data_dir: Path | str) -> dict[int, set[str]]:
    """Scan product JSON directory and build {product_id: set(sellable_colors)} mapping."""
    path = Path(data_dir)
    if not path.is_dir():
        logger.warning("상품 데이터 디렉터리가 존재하지 않습니다: %s", path)
        return {}

    sellable_map: dict[int, set[str]] = {}
    for json_file in path.rglob("*.json"):
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                product = json.load(f)
            pid = product.get("product_id")
            if pid is not None:
                colors = extract_sellable_colors(product)
                mapping_colors = {
                    m["color_raw"].strip().lower()
                    for m in product.get("color_image_mappings") or []
                    if isinstance(m.get("color_raw"), str)
                }
                # 인덱서(filter_sellable_color_mappings)와 동일하게,
                # 색상 매핑과 겹치는 색상이 전혀 없으면(예: 사이즈 옵션만 있는 상품)
                # 오삭제를 방지하기 위해 필터링 대상에서 제외하여 포인트를 보존한다.
                if colors and (not mapping_colors or (colors & mapping_colors)):
                    sellable_map[int(pid)] = colors
        except Exception as exc:
            logger.debug("JSON 읽기 실패 (%s): %s", json_file, exc)

    logger.info("총 %d개 상품의 판매 색상 옵션 매핑 로드 완료", len(sellable_map))
    return sellable_map


def scan_and_purge_unsellable_points(
    client: QdrantClient,
    collection_name: str,
    sellable_map: dict[int, set[str]],
    dry_run: bool = True,
    batch_size: int = 500,
) -> dict[str, Any]:
    """Scroll through Qdrant collection and purge points with colors not in sellable_map."""
    offset = None
    total_scanned = 0
    unsellable_points: list[dict[str, Any]] = []

    logger.info("Qdrant 컬렉션 '%s' 스캔 시작 (dry_run=%s)", collection_name, dry_run)

    while True:
        points, next_offset = client.scroll(
            collection_name=collection_name,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            break

        total_scanned += len(points)
        for pt in points:
            payload = pt.payload or {}
            pid = payload.get("product_id")
            if pid is None or int(pid) not in sellable_map:
                continue

            raw_color = payload.get("color_raw")
            if not raw_color or not isinstance(raw_color, str):
                continue

            cleaned_color = raw_color.strip().lower()
            allowed_colors = sellable_map[int(pid)]
            if cleaned_color not in allowed_colors:
                unsellable_points.append({
                    "point_id": pt.id,
                    "product_id": int(pid),
                    "product_name": payload.get("product_name"),
                    "color_raw": raw_color,
                    "allowed_colors": list(allowed_colors),
                })

        if next_offset is None:
            break
        offset = next_offset

    logger.info(
        "스캔 완료: 총 %d개 포인트 확인, 비판매 색상 포인트 %d개 발견",
        total_scanned,
        len(unsellable_points),
    )

    deleted_count = 0
    if unsellable_points:
        point_ids_to_delete = [p["point_id"] for p in unsellable_points]
        for p in unsellable_points[:10]:
            logger.info(
                "  - 비판매 포인트: PID=%s (%s), 색상='%s' (판매가능: %s)",
                p["product_id"],
                p["product_name"],
                p["color_raw"],
                p["allowed_colors"],
            )
        if len(unsellable_points) > 10:
            logger.info("  ... 외 %d개 포인트", len(unsellable_points) - 10)

        if not dry_run:
            logger.info("Qdrant에서 %d개 포인트 삭제 진행 중...", len(point_ids_to_delete))
            # Delete in chunks of 500
            for i in range(0, len(point_ids_to_delete), 500):
                chunk = point_ids_to_delete[i:i + 500]
                client.delete(
                    collection_name=collection_name,
                    points_selector=models.PointIdsList(points=chunk),
                    wait=True,
                )
            deleted_count = len(point_ids_to_delete)
            logger.info("🎉 %d개 비판매 포인트 삭제 완료!", deleted_count)
        else:
            logger.info("💡 [Dry-run 모드] 실제 삭제는 수행되지 않았습니다. 적용하려면 --dry-run 옵션을 제외하고 실행하세요.")

    return {
        "total_scanned": total_scanned,
        "unsellable_found": len(unsellable_points),
        "deleted_count": deleted_count,
        "dry_run": dry_run,
        "details": unsellable_points,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Qdrant 컬렉션에서 실제 판매 옵션에 없는 비판매 색상 포인트를 삭제합니다."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help="상품 JSON 디렉터리 경로",
    )
    parser.add_argument(
        "--qdrant-url",
        default=DEFAULT_QDRANT_URL,
        help="Qdrant 서버 URL",
    )
    parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION,
        help="대상 Qdrant 컬렉션 이름 또는 별칭 (기본값: musinsa_products)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="실제 삭제하지 않고 대상 포인트만 출력",
    )
    return parser


def main() -> int:
    """CLI 진입점: 판매 색상 맵을 로드하고 Qdrant의 미판매 포인트를 정리한다."""
    parser = build_parser()
    args = parser.parse_args()

    sellable_map = build_sellable_colors_map(args.data_dir)
    if not sellable_map:
        logger.error("판매 색상 정보를 읽지 못했습니다. 경로를 확인하세요: %s", args.data_dir)
        return 1

    try:
        client = QdrantClient(url=args.qdrant_url, timeout=60)
        client.get_collections()
    except Exception as exc:
        logger.error("Qdrant 연결 실패 (%s): %s", args.qdrant_url, exc)
        return 1

    scan_and_purge_unsellable_points(
        client=client,
        collection_name=args.collection,
        sellable_map=sellable_map,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
