"""Model-free vector-run logic shared by the embedding and import Jobs.

A point is one product + color variant + evidence image. Point IDs, payloads and part
boundaries are deterministic so an interrupted run resumes without duplicates.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlparse
import uuid

VECTOR_SIZE = 512
CATEGORIES = {"상의", "하의", "아우터", "모자", "신발"}
COLORS = {"black", "white", "ivory", "beige", "gray", "charcoal", "navy", "blue", "green",
          "khaki", "brown", "red", "pink", "purple", "yellow", "orange", "multi", "etc"}
IMAGE_HOSTS = {"image.msscdn.net", "image.musinsa.com", "image.musinsa.co.kr"}
IMAGE_BASE_URL = "https://image.msscdn.net"
MEASUREMENT_KEYS = {
    "상의": {"총장": "top_length", "어깨너비": "shoulder", "가슴단면": "chest", "소매길이": "sleeve",
           "밑단단면": "top_hem", "소매부리단면": "cuff", "암홀": "armhole"},
    "하의": {"총장": "bottom_length", "허리단면": "waist", "엉덩이단면": "hip", "허벅지단면": "thigh",
           "밑위": "rise", "밑단단면": "bottom_hem"},
    "신발": {"발길이": "foot_length", "발볼": "foot_width", "발목높이": "ankle_height", "굽높이": "heel_height"},
    "모자": {"머리둘레": "head_circumference", "챙길이": "brim_length", "깊이": "depth"},
}
MEASUREMENT_KEYS["아우터"] = MEASUREMENT_KEYS["상의"]
# Keyword/integer indexes used by recommendation-service filters and the Qdrant contract.
PAYLOAD_INDEXES = {"product_id": "integer", "price": "integer", "category": "keyword",
                   "subcategory": "keyword", "color_normalized": "keyword", "normalized_color": "keyword",
                   "color_variant": "keyword", "brand": "keyword", "brand_name": "keyword"}
REQUIRED_PAYLOAD = ("product_id", "color_variant", "color_raw", "color_normalized", "normalized_color",
                    "brand", "brand_name", "category", "price", "image_url", "image_key")


def color_key(raw: str) -> str:
    return raw.strip().lower()


def normalize_image_url(value: object) -> str | None:
    """Same rule as crawler cloud_media.normalize_image_url, used to find the stored copy."""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = IMAGE_BASE_URL + value
    parsed = urlparse(value)
    if (parsed.scheme != "https" or parsed.hostname not in IMAGE_HOSTS
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        return None
    return value


def point_id(product_id: int, variant_key: str, image_key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{product_id}|{variant_key}|{image_key}"))


def verify_bundle_against_manifest(data_root: Path, manifest: dict) -> dict[str, str]:
    """Return product_id -> relative path after checking every file against the curated manifest."""
    expected = {record["path"]: record for record in manifest.get("products") or []}
    if not expected:
        raise ValueError("Curated manifest has no products")
    found = {path.relative_to(data_root).as_posix(): path for path in sorted(data_root.rglob("*.json"))}
    if set(found) != set(expected):
        missing, extra = sorted(set(expected) - set(found)), sorted(set(found) - set(expected))
        raise ValueError(f"Approved data differs from curated manifest: missing={missing[:5]} extra={extra[:5]}")
    products = {}
    for relative, path in found.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected[relative]["sha256"]:
            raise ValueError(f"Approved product differs from curated manifest: {relative}")
        products[str(expected[relative]["product_id"])] = relative
    return products


def normalize_sizes(category: str, rows: list) -> list[dict]:
    keys = MEASUREMENT_KEYS.get(category, {})
    sizes = []
    for row in rows or []:
        measured = {}
        for name, value in (row.get("measurements") or {}).items():
            if name in keys:
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if math.isfinite(number) and number > 0:
                    measured[keys[name]] = number
        if measured:
            sizes.append({"size": row.get("size"), "sequence": row.get("sequence", 0), "measurements": measured})
    return sizes


def make_payload(product: dict, raw_color: str, normalized: str, image_url: str, image_key: str) -> dict:
    category = (product.get("dataset") or {}).get("logical_category")
    if category not in CATEGORIES:
        raise ValueError(f"Unknown product category: {category}")
    if normalized not in COLORS:
        raise ValueError(f"Color outside the fixed palette: {normalized}")
    brand = (product.get("brand") or {}).get("name") or ""
    return {
        "product_id": int(product["product_id"]),
        "product_name": product.get("name") or "",
        "brand": brand,
        "brand_name": brand,
        "category": category,
        "subcategory": (product.get("category") or {}).get("categoryDepth2Title") or "",
        "price": int((product.get("price") or {}).get("normal") or 0),
        "season_candidates": (product.get("season") or {}).get("primary_candidates") or [],
        "color_variant": raw_color.strip(),
        "color_raw": raw_color,
        "color_normalized": [normalized],
        "normalized_color": normalized,
        "features": product.get("features") or {},
        "sizes": normalize_sizes(category, (product.get("size") or {}).get("measurements")),
        "image_url": image_url,
        "image_key": image_key,
        "product_url": product.get("source_url") or "",
    }


def plan_product_points(product: dict, color_map: dict[str, str], image_manifest: dict | None) -> tuple[list[dict], list[dict], int]:
    """Return (points, failures, duplicate_count) for one product without loading images."""
    product_id = int(product["product_id"])
    stored = {}
    for record in (image_manifest or {}).get("images") or []:
        url = normalize_image_url(record.get("source_url"))
        if url and record.get("s3_key"):
            stored[url] = record
    points, failures, seen, duplicates = [], [], set(), 0
    for mapping in product.get("color_image_mappings") or []:
        raw = mapping.get("color_raw") or ""
        failure = {"product_id": product_id, "color_raw": raw, "image_url": mapping.get("image_url")}
        key = color_key(raw)
        if key not in color_map:
            failures.append({**failure, "reason": "unmapped_color"})
            continue
        url = normalize_image_url(mapping.get("image_url"))
        record = stored.get(url) if url else None
        if record is None:
            failures.append({**failure, "reason": "image_not_stored"})
            continue
        identifier = point_id(product_id, key, record["s3_key"])
        if identifier in seen:
            duplicates += 1
            continue
        seen.add(identifier)
        points.append({"point_id": identifier, "product_id": product_id, "image_key": record["s3_key"],
                       "image_sha256": record.get("sha256"),
                       "payload": make_payload(product, raw, color_map[key], url, record["s3_key"])})
    return points, failures, duplicates


def partition(points: list[dict], part_size: int) -> list[list[dict]]:
    ordered = sorted(points, key=lambda point: point["point_id"])
    return [ordered[index:index + part_size] for index in range(0, len(ordered), part_size)]


def part_name(index: int) -> str:
    return f"part-{index:05d}.jsonl"


def plan_digest(parts: list[list[dict]], model_revision: str) -> str:
    """Fingerprint of the point order, payloads and model so a resume cannot mix different plans."""
    digest = hashlib.sha256(model_revision.encode())
    for part in parts:
        for point in part:
            digest.update(json.dumps([point["point_id"], point["image_sha256"], point["payload"]],
                                     ensure_ascii=False, sort_keys=True).encode())
        digest.update(b"|")
    return digest.hexdigest()


def invalid_vector_reason(vector: object) -> str | None:
    if not isinstance(vector, list) or len(vector) != VECTOR_SIZE:
        return "wrong_dimension"
    if not all(isinstance(value, (int, float)) and math.isfinite(value) for value in vector):
        return "non_finite"
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return "zero_vector"
    return None


def payload_problems(payload: dict) -> list[str]:
    problems = [f"missing:{key}" for key in REQUIRED_PAYLOAD if key not in payload]
    colors = payload.get("color_normalized")
    if not isinstance(colors, list) or len(colors) != 1 or colors[0] != payload.get("normalized_color"):
        problems.append("color_fields_disagree")
    elif colors[0] not in COLORS:
        problems.append("color_outside_palette")
    return problems
