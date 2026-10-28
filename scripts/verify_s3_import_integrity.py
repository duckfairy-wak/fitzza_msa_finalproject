"""Verify crawler S3 artifacts and an optional staging DB summary for FITZZA-285."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


@dataclass(frozen=True)
class ExpectedCounts:
    products: int = 3000
    images: int = 28569
    image_failures: int = 64
    reviews: int = 87434


def read_object(client: Any, bucket: str, key: str) -> bytes:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    try:
        return body.read()
    finally:
        body.close()


def list_keys(client: Any, bucket: str, prefix: str) -> list[str]:
    paginator = client.get_paginator("list_objects_v2")
    return [
        item["Key"]
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix)
        for item in page.get("Contents", [])
        if item["Key"] != prefix and not item["Key"].endswith("/")
    ]


def load_json(client: Any, bucket: str, key: str) -> Any:
    return json.loads(read_object(client, bucket, key))


def product_id_from_key(key: str) -> str:
    return Path(key).stem


def validate_manifest(client: Any, bucket: str, prefix: str) -> tuple[set[str], set[str], list[str]]:
    manifest = load_json(client, bucket, f"{prefix}/curated/manifest.json")
    entries = manifest.get("products") or manifest.get("files") or manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("curated manifest must contain a product list")
    product_ids: set[str] = set()
    manifest_keys: set[str] = set()
    errors: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("manifest entry is not an object")
            continue
        product_id = str(entry.get("product_id", ""))
        key = entry.get("s3_key") or entry.get("object_key") or entry.get("path")
        digest = entry.get("sha256") or entry.get("checksum")
        if not product_id or product_id in product_ids:
            errors.append(f"duplicate or missing product_id: {product_id}")
            continue
        product_ids.add(product_id)
        if not isinstance(key, str) or not isinstance(digest, str):
            errors.append(f"{product_id}: manifest path or sha256 missing")
            continue
        manifest_keys.add(key)
        try:
            actual = hashlib.sha256(read_object(client, bucket, key)).hexdigest()
        except ClientError as error:
            errors.append(f"{product_id}: object read failed at s3://{bucket}/{key}: {error.response['Error']['Code']}")
            continue
        if actual != digest:
            errors.append(f"{product_id}: sha256 mismatch at s3://{bucket}/{key}")
    return product_ids, manifest_keys, errors


def count_reviews(client: Any, bucket: str, keys: Iterable[str], product_ids: set[str]) -> tuple[int, list[str]]:
    total = 0
    errors: list[str] = []
    for key in keys:
        try:
            document = load_json(client, bucket, key)
        except (ClientError, json.JSONDecodeError, UnicodeDecodeError) as error:
            errors.append(f"review document read failed at s3://{bucket}/{key}: {type(error).__name__}")
            continue
        reviews = document.get("reviews")
        key_product_id = product_id_from_key(key)
        document_product_id = document.get("product_id")
        product_id = str(document_product_id or key_product_id)
        if document_product_id is not None and str(document_product_id) != key_product_id:
            errors.append(f"review product id does not match file name at s3://{bucket}/{key}")
        if product_id not in product_ids:
            errors.append(f"review foreign key missing: {product_id} at s3://{bucket}/{key}")
        if not isinstance(reviews, list):
            errors.append(f"review list missing at s3://{bucket}/{key}")
            continue
        declared = document.get("collected_review_count")
        if declared is not None and declared != len(reviews):
            errors.append(f"review count mismatch at s3://{bucket}/{key}")
        total += len(reviews)
    return total, errors


def count_image_failures(client: Any, bucket: str, keys: Iterable[str]) -> tuple[int, list[str]]:
    total = 0
    errors: list[str] = []
    for key in keys:
        try:
            document = load_json(client, bucket, key)
        except (ClientError, json.JSONDecodeError, UnicodeDecodeError) as error:
            errors.append(f"image failure audit read failed at s3://{bucket}/{key}: {type(error).__name__}")
            continue
        failures = document.get("failures")
        if not isinstance(failures, list):
            errors.append(f"image failure audit must contain a failures array at s3://{bucket}/{key}")
            continue
        total += len(failures)
    return total, errors


def load_db_summary(path: Path | None) -> dict[str, int] | None:
    if path is None:
        return None
    summary = json.loads(path.read_text(encoding="utf-8"))
    required = {"product_count", "distinct_product_count", "image_count", "review_count", "orphan_image_count", "orphan_review_count"}
    if set(summary) != required or any(not isinstance(summary[key], int) for key in required):
        raise ValueError("DB summary must contain the documented integer fields exactly")
    return summary


def verify(client: Any, bucket: str, prefix: str, expected: ExpectedCounts, db_summary: dict[str, int] | None) -> dict[str, Any]:
    product_ids, manifest_keys, errors = validate_manifest(client, bucket, prefix)
    curated_keys = set(list_keys(client, bucket, f"{prefix}/curated/data/"))
    missing_curated_keys = manifest_keys - curated_keys
    unlisted_curated_keys = curated_keys - manifest_keys
    for key in sorted(missing_curated_keys):
        errors.append(f"manifest object missing from curated data: s3://{bucket}/{key}")
    for key in sorted(unlisted_curated_keys):
        errors.append(f"curated object missing from manifest: s3://{bucket}/{key}")
    image_keys = [key for key in list_keys(client, bucket, f"{prefix}/images/products/") if not key.endswith("/manifest.json")]
    failure_keys = list_keys(client, bucket, f"{prefix}/audit/image-download-failures/products/")
    review_keys = list_keys(client, bucket, f"{prefix}/reviews/data/")
    image_failure_count, failure_errors = count_image_failures(client, bucket, failure_keys)
    errors.extend(failure_errors)
    review_count, review_errors = count_reviews(client, bucket, review_keys, product_ids)
    errors.extend(review_errors)

    for key in image_keys:
        parts = key.removeprefix(f"{prefix}/images/products/").split("/", 1)
        if not parts or parts[0] not in product_ids:
            errors.append(f"image product id missing: s3://{bucket}/{key}")

    actual = {"products": len(product_ids), "images": len(image_keys), "image_failures": image_failure_count, "reviews": review_count}
    expected_values = expected.__dict__
    for name, value in expected_values.items():
        if actual[name] != value:
            errors.append(f"{name}: expected {value}, got {actual[name]}")

    if db_summary is not None:
        if db_summary["product_count"] != actual["products"] or db_summary["distinct_product_count"] != actual["products"]:
            errors.append("DB product count or uniqueness does not match S3")
        if db_summary["image_count"] != actual["images"] or db_summary["review_count"] != actual["reviews"]:
            errors.append("DB image or review count does not match S3")
        if db_summary["orphan_image_count"] or db_summary["orphan_review_count"]:
            errors.append("DB contains orphan image or review rows")

    return {"schema_version": 1, "bucket": bucket, "prefix": prefix, "expected": expected_values, "actual": actual, "db_summary": db_summary, "errors": errors, "ok": not errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", default="pipeline/runs/collection-20261025-01")
    parser.add_argument("--db-summary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-key")
    args = parser.parse_args()
    client = boto3.client("s3", config=Config(retries={"mode": "standard", "total_max_attempts": 3}, connect_timeout=5, read_timeout=30))
    try:
        report = verify(client, args.bucket, args.prefix.rstrip("/"), ExpectedCounts(), load_db_summary(args.db_summary))
        payload = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(payload + b"\n")
        if args.report_key:
            client.put_object(Bucket=args.bucket, Key=args.report_key, Body=payload, ContentType="application/json", ServerSideEncryption="AES256")
        print(json.dumps({"ok": report["ok"], "output": str(args.output)}))
        return 0 if report["ok"] else 1
    except (ClientError, ValueError, json.JSONDecodeError) as error:
        print(f"Integrity verification failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
