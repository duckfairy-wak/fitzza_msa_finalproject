"""Validate a completed crawler run before DB import."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from typing import Any


def _json(s3: Any, bucket: str, key: str) -> dict[str, Any]:
    response = s3.get_object(Bucket=bucket, Key=key)
    try:
        return json.loads(response["Body"].read())
    finally:
        response["Body"].close()


def _keys(s3: Any, bucket: str, prefix: str) -> list[str]:
    result: list[str] = []
    token: str | None = None
    while True:
        args = {"Bucket": bucket, "Prefix": prefix}
        if token:
            args["ContinuationToken"] = token
        page = s3.list_objects_v2(**args)
        result.extend(obj["Key"] for obj in page.get("Contents", []))
        if not page.get("IsTruncated"):
            return result
        token = page["NextContinuationToken"]


def validate_run(s3: Any, bucket: str, prefix: str) -> dict[str, Any]:
    prefix = prefix.rstrip("/") + "/"
    manifest = _json(s3, bucket, f"{prefix}curated/manifest.json")
    expected = manifest.get("files", {})
    products = _keys(s3, bucket, f"{prefix}curated/data/")
    products = [key for key in products if key.endswith(".json")]
    reviews = [key for key in _keys(s3, bucket, f"{prefix}reviews/data/") if key.endswith(".json")]
    images = [key for key in _keys(s3, bucket, f"{prefix}images/products/") if not key.endswith("/")]
    failures = [key for key in _keys(s3, bucket, f"{prefix}audit/image-download-failures/products/") if key.endswith(".json")]

    product_ids = [key.rsplit("/", 1)[-1][:-5] for key in products]
    duplicate_ids = sorted(pid for pid, count in Counter(product_ids).items() if count > 1)
    review_ids = {key.rsplit("/", 1)[-1][:-5] for key in reviews}
    missing_review_products = sorted(set(product_ids) - review_ids)

    manifest_mismatches: list[str] = []
    for relative, expected_hash in expected.items():
        key = f"{prefix}curated/{relative}"
        response = s3.get_object(Bucket=bucket, Key=key)
        try:
            actual_hash = hashlib.sha256(response["Body"].read()).hexdigest()
        finally:
            response["Body"].close()
        if actual_hash != expected_hash:
            manifest_mismatches.append(relative)

    report = {
        "run_prefix": prefix,
        "product_json_count": len(products),
        "review_json_count": len(reviews),
        "product_image_count": len(images),
        "image_failure_audit_count": len(failures),
        "duplicate_product_ids": duplicate_ids,
        "products_without_review_file": missing_review_products,
        "manifest_sha256_mismatches": manifest_mismatches,
        "valid": not (duplicate_ids or manifest_mismatches),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--profile", help="AWS CLI profile name")
    args = parser.parse_args()
    import boto3

    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
    report = validate_run(session.client("s3"), args.bucket, args.prefix)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
