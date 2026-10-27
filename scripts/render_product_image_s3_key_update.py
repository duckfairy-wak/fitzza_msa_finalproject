"""Rewrite product image columns to S3 object keys from collection image manifests.

Reads ``images/products/<product_id>/manifest.json`` produced by the crawler and
renders an idempotent SQL script that:

* replaces ``product_image`` rows with ``kind=product`` object keys (sequence order)
* sets ``product.image_url`` to the first product key
* rewrites ``product_size_guide.guide_image_url`` when a ``size-guide`` key exists
* rewrites ``color_image_mappings`` / ``product_option.image_url`` by matching
  Musinsa ``source_url`` → ``s3_key``

Failed download entries (guide: 64 image failures across product audit files) are
skipped; products keep whatever keys the manifest successfully recorded.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProductImages:
    product_id: int
    product_keys: list[str]
    size_guide_key: str | None
    url_to_key: dict[str, str]


def load_manifest(path: Path) -> ProductImages | None:
    document = json.loads(path.read_text(encoding="utf-8"))
    raw_id = document.get("product_id")
    try:
        product_id = int(raw_id)
    except (TypeError, ValueError):
        return None
    if path.parent.name != str(product_id):
        raise ValueError(f"{path}: folder name does not match product_id")

    product_keys: list[str] = []
    size_guide_key: str | None = None
    url_to_key: dict[str, str] = {}
    for image in document.get("images") or []:
        if not isinstance(image, dict):
            continue
        key = image.get("s3_key")
        source_url = image.get("source_url")
        kind = image.get("kind")
        if not isinstance(key, str) or not key or len(key) > 500:
            continue
        if isinstance(source_url, str) and source_url:
            url_to_key[source_url] = key
        if kind == "product":
            product_keys.append(key)
        elif kind == "size-guide" and size_guide_key is None:
            size_guide_key = key
    return ProductImages(product_id, product_keys, size_guide_key, url_to_key)


def load_all_manifests(images_root: Path) -> dict[int, ProductImages]:
    loaded: dict[int, ProductImages] = {}
    for path in sorted(images_root.glob("*/manifest.json")):
        parsed = load_manifest(path)
        if parsed is None or not parsed.product_keys:
            continue
        loaded[parsed.product_id] = parsed
    if not loaded:
        raise ValueError(f"no image manifests with product keys under {images_root}")
    return loaded


def load_failure_image_count(failures_root: Path | None) -> tuple[int, int]:
    if failures_root is None or not failures_root.exists():
        return 0, 0
    files = sorted(failures_root.glob("*.json"))
    entries = 0
    for path in files:
        document = json.loads(path.read_text(encoding="utf-8"))
        entries += len(document.get("failures") or [])
    return len(files), entries


def rewrite_color_mappings(raw: Any, url_to_key: dict[str, str]) -> str | None:
    if not isinstance(raw, list) or not raw:
        return None
    rewritten: list[dict[str, Any]] = []
    changed = False
    for item in raw:
        if not isinstance(item, dict):
            continue
        # DB jsonb uses camelCase from ColorImageMappingValue; curated JSON uses snake.
        image_url = item.get("imageUrl")
        if image_url is None:
            image_url = item.get("image_url")
        key = url_to_key.get(image_url) if isinstance(image_url, str) else None
        product_id = item.get("productId", item.get("product_id"))
        color_raw = item.get("colorRaw", item.get("color_raw"))
        if key is not None:
            changed = True
            image_url = key
        if not isinstance(color_raw, str) or not color_raw.strip():
            continue
        rewritten.append(
            {
                "productId": product_id,
                "colorRaw": color_raw.strip(),
                "imageUrl": image_url,
            }
        )
    if not rewritten:
        return None
    if not changed:
        return None
    return json.dumps(rewritten, ensure_ascii=False, separators=(",", ":"))


def load_color_mapping_updates(
    data_root: Path, manifests: dict[int, ProductImages]
) -> list[tuple[int, str]]:
    updates: list[tuple[int, str]] = []
    for path in data_root.glob("*/*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        product_id = document.get("product_id")
        if not isinstance(product_id, int) or product_id not in manifests:
            continue
        global_urls = manifests[product_id].url_to_key
        # Also allow cross-product URL map for shared CDN URLs (rare).
        payload = rewrite_color_mappings(document.get("color_image_mappings"), global_urls)
        if payload is not None:
            updates.append((product_id, payload))
    return updates


def _copy(output: io.StringIO, table: str, columns: list[str], rows: list[list[Any]]) -> None:
    output.write(
        f"COPY {table} ({', '.join(columns)}) "
        "FROM STDIN WITH (FORMAT csv, HEADER true, NULL '');\n"
    )
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    output.write("\\.\n")


def render_sql(
    manifests: dict[int, ProductImages],
    color_updates: list[tuple[int, str]],
    *,
    run_id: str,
) -> str:
    output = io.StringIO(newline="")
    output.write("\\set ON_ERROR_STOP on\nBEGIN;\n")
    output.write(f"-- product image s3_key remap run_id={run_id}\n")

    output.write(
        "CREATE TEMP TABLE image_key_product ("
        "product_id bigint, image_url varchar(500), sequence integer"
        ") ON COMMIT DROP;\n"
    )
    output.write(
        "CREATE TEMP TABLE image_key_thumb ("
        "product_id bigint, image_url varchar(500)"
        ") ON COMMIT DROP;\n"
    )
    output.write(
        "CREATE TEMP TABLE image_key_size_guide ("
        "product_id bigint, guide_image_url varchar(500)"
        ") ON COMMIT DROP;\n"
    )
    output.write(
        "CREATE TEMP TABLE image_key_url_map ("
        "source_url varchar(500), object_key varchar(500)"
        ") ON COMMIT DROP;\n"
    )
    output.write(
        "CREATE TEMP TABLE image_key_color_map ("
        "product_id bigint, color_image_mappings jsonb"
        ") ON COMMIT DROP;\n"
    )

    image_rows: list[list[Any]] = []
    thumb_rows: list[list[Any]] = []
    size_rows: list[list[Any]] = []
    url_rows: list[list[Any]] = []
    seen_urls: set[str] = set()
    for product in manifests.values():
        for sequence, key in enumerate(product.product_keys):
            image_rows.append([product.product_id, key, sequence])
        thumb_rows.append([product.product_id, product.product_keys[0]])
        if product.size_guide_key:
            size_rows.append([product.product_id, product.size_guide_key])
        for source_url, key in product.url_to_key.items():
            if source_url in seen_urls or len(source_url) > 500:
                continue
            seen_urls.add(source_url)
            url_rows.append([source_url, key])

    _copy(output, "image_key_product", ["product_id", "image_url", "sequence"], image_rows)
    _copy(output, "image_key_thumb", ["product_id", "image_url"], thumb_rows)
    _copy(output, "image_key_size_guide", ["product_id", "guide_image_url"], size_rows)
    _copy(output, "image_key_url_map", ["source_url", "object_key"], url_rows)
    _copy(
        output,
        "image_key_color_map",
        ["product_id", "color_image_mappings"],
        [[product_id, payload] for product_id, payload in color_updates],
    )

    output.write(
        "DELETE FROM product_service.product_image pi "
        "USING image_key_thumb t WHERE pi.product_id = t.product_id;\n"
    )
    output.write(
        "INSERT INTO product_service.product_image (product_id, image_url, sequence) "
        "SELECT product_id, image_url, sequence FROM image_key_product;\n"
    )
    output.write(
        "UPDATE product_service.product AS p "
        "SET image_url = t.image_url, updated_at = NOW() "
        "FROM image_key_thumb t WHERE p.product_id = t.product_id;\n"
    )
    output.write(
        "UPDATE product_service.product_size_guide AS g "
        "SET guide_image_url = s.guide_image_url "
        "FROM image_key_size_guide s WHERE g.product_id = s.product_id;\n"
    )
    output.write(
        "UPDATE product_service.product AS p "
        "SET color_image_mappings = c.color_image_mappings, updated_at = NOW() "
        "FROM image_key_color_map c WHERE p.product_id = c.product_id;\n"
    )
    output.write(
        "UPDATE product_service.product_option AS o "
        "SET image_url = m.object_key "
        "FROM image_key_url_map m "
        "WHERE o.image_url = m.source_url;\n"
    )
    output.write("COMMIT;\n")
    return output.getvalue()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Render SQL that remaps product images to crawler S3 object keys."
    )
    parser.add_argument(
        "--images",
        type=Path,
        required=True,
        help="local images/products directory containing per-product manifest.json",
    )
    parser.add_argument(
        "--data",
        type=Path,
        required=True,
        help="curated/data directory (for color_image_mappings rewrite)",
    )
    parser.add_argument(
        "--image-failures",
        type=Path,
        help="audit/image-download-failures/products (counted only)",
    )
    parser.add_argument("--run-id", default="collection-20261025-01")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manifests = load_all_manifests(args.images)
    color_updates = load_color_mapping_updates(args.data, manifests)
    failure_files, failure_entries = load_failure_image_count(args.image_failures)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_sql(manifests, color_updates, run_id=args.run_id),
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "products_with_keys": len(manifests),
                "product_image_rows": sum(len(item.product_keys) for item in manifests.values()),
                "size_guide_updates": sum(1 for item in manifests.values() if item.size_guide_key),
                "color_mapping_updates": len(color_updates),
                "url_map_entries": sum(len(item.url_to_key) for item in manifests.values()),
                "image_failure_files": failure_files,
                "image_failure_entries": failure_entries,
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
