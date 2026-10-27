"""Build a review import report from review JSON objects in an S3 run prefix."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from typing import Any

from src.cloud_media import put_json, utc_now


def _keys(s3: Any, bucket: str, prefix: str) -> list[str]:
    keys: list[str] = []
    token = None
    while True:
        params = {"Bucket": bucket, "Prefix": prefix}
        if token:
            params["ContinuationToken"] = token
        page = s3.list_objects_v2(**params)
        keys.extend(obj["Key"] for obj in page.get("Contents", []))
        if not page.get("IsTruncated"):
            return keys
        token = page["NextContinuationToken"]


def build_review_report(s3: Any, bucket: str, prefix: str) -> dict[str, Any]:
    prefix = prefix.rstrip("/") + "/"
    keys = sorted(key for key in _keys(s3, bucket, f"{prefix}reviews/data/")
                  if key.endswith(".json"))
    product_ids: list[str] = []
    review_count = 0
    reported_count = 0
    truncated: list[str] = []
    duplicate_review_ids = 0
    for key in keys:
        response = s3.get_object(Bucket=bucket, Key=key)
        try:
            data = json.loads(response["Body"].read())
        finally:
            response["Body"].close()
        product_id = str(data.get("product_id") or key.rsplit("/", 1)[-1][:-5])
        product_ids.append(product_id)
        reviews = data.get("reviews") if isinstance(data.get("reviews"), list) else []
        review_count += len(reviews)
        reported_count += int(data.get("reported_review_count") or 0)
        if data.get("truncated"):
            truncated.append(product_id)
        ids = [item.get("source_review_id") for item in reviews if isinstance(item, dict)]
        duplicate_review_ids += len(ids) - len(set(ids))
    duplicates = sorted(product_id for product_id, count in Counter(product_ids).items() if count > 1)
    return {
        "schema_version": 1,
        "source": "musinsa",
        "generated_at": utc_now(),
        # Compatibility fields consumed by render_crawled_review_import.py.
        "selected": len(keys),
        "completed": len(keys),
        "selected_product_count": len(keys),
        "completed_product_count": len(keys),
        "failed_product_count": len(duplicates),
        "failed_products": duplicates,
        "review_file_count": len(keys),
        "review_count": review_count,
        "reported_review_count": reported_count,
        "truncated_product_ids": truncated,
        "duplicate_product_ids": duplicates,
        "duplicate_review_id_count": duplicate_review_ids,
        "review_images_collected": 0,
        "valid": not duplicates and duplicate_review_ids == 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--profile")
    args = parser.parse_args()
    import boto3
    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
    report = build_review_report(session.client("s3"), args.bucket, args.prefix)
    put_json(session.client("s3"), args.bucket,
             f"{args.prefix.rstrip('/')}/reviews/report.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
