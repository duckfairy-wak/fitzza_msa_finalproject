"""Restore collected S3 JSON objects to the original external schema contract."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from typing import Callable

import boto3
from botocore.config import Config

from src.cloud_media import object_exists, put_json, utc_now
from src.curate_dataset import external_product_contract


def read_json(s3, bucket: str, key: str) -> dict:
    response = s3.get_object(Bucket=bucket, Key=key)
    with response["Body"] as body:
        return json.load(body)


def encode_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def put_document(s3, bucket: str, key: str, value: object) -> bytes:
    body = encode_json(value)
    s3.put_object(Bucket=bucket, Key=key, Body=body, ContentType="application/json",
                  ServerSideEncryption="AES256")
    return body


def restore_product_image_manifest(document: dict) -> tuple[dict, list[dict]]:
    restored = dict(document)
    failures = restored.pop("failures", [])
    restored.pop("failed_image_count", None)
    return restored, failures if isinstance(failures, list) else []


def restore_review_document(document: dict) -> dict:
    restored = dict(document)
    restored.pop("failed_review_image_count", None)
    reviews = []
    for value in restored.get("reviews") or []:
        review = dict(value)
        review.pop("image_failures", None)
        review.setdefault("image_files", [])
        reviews.append(review)
    restored["reviews"] = reviews
    return restored


def restore_status_document(document: dict) -> dict:
    restored = dict(document)
    restored.pop("failed_images_this_run", None)
    restored.pop("product_image_failures_this_run", None)
    restored.pop("review_image_failures_this_run", None)
    return restored


def list_json_keys(s3, bucket: str, prefix: str) -> list[str]:
    paginator = s3.get_paginator("list_objects_v2")
    return [
        item["Key"]
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix)
        for item in page.get("Contents", [])
        if item["Key"].endswith(".json")
    ]


def run_parallel(label: str, keys: list[str], worker: Callable[[str], object],
                 workers: int) -> list[object]:
    results = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(worker, key): key for key in keys}
        for completed, future in enumerate(as_completed(futures), 1):
            results.append(future.result())
            if completed % 250 == 0 or completed == len(keys):
                print(json.dumps({"stage": label, "completed": completed,
                    "total": len(keys)}, ensure_ascii=False), flush=True)
    return results


def restore_run(s3, bucket: str, run_id: str, workers: int) -> dict:
    prefix = f"pipeline/runs/{run_id}"
    manifest_key = f"{prefix}/curated/manifest.json"
    report_key = f"{prefix}/curated/report.json"
    manifest = read_json(s3, bucket, manifest_key)
    report = read_json(s3, bucket, report_key)

    product_records = manifest.get("products") or []
    product_keys = [record["s3_key"] for record in product_records]

    def restore_product(key: str) -> tuple[str, str]:
        restored = external_product_contract(read_json(s3, bucket, key))
        body = put_document(s3, bucket, key, restored)
        return key, hashlib.sha256(body).hexdigest()

    digests = dict(run_parallel("curated-products", product_keys,
                                restore_product, workers))
    for record in product_records:
        record["sha256"] = digests[record["s3_key"]]
        report["files"][f"data/{record['path']}"] = record["sha256"]
    put_document(s3, bucket, report_key, report)
    put_document(s3, bucket, manifest_key, manifest)

    image_keys = [key for key in list_json_keys(
        s3, bucket, f"{prefix}/images/products/") if key.endswith("/manifest.json")]

    def restore_image_manifest(key: str) -> int:
        document = read_json(s3, bucket, key)
        restored, failures = restore_product_image_manifest(document)
        if failures:
            product_id = str(restored["product_id"])
            audit_key = f"{prefix}/audit/image-download-failures/products/{product_id}.json"
            if not object_exists(s3, bucket, audit_key):
                put_json(s3, bucket, audit_key, {"schema_version": 1,
                    "product_id": product_id, "recorded_at": utc_now(),
                    "failures": failures})
        if restored != document:
            put_document(s3, bucket, key, restored)
        return len(failures)

    image_failure_count = sum(run_parallel(
        "product-image-manifests", image_keys, restore_image_manifest, workers))

    review_keys = list_json_keys(s3, bucket, f"{prefix}/reviews/data/")

    def restore_review(key: str) -> bool:
        document = read_json(s3, bucket, key)
        restored = restore_review_document(document)
        if restored != document:
            put_document(s3, bucket, key, restored)
            return True
        return False

    changed_reviews = sum(run_parallel(
        "review-documents", review_keys, restore_review, workers))

    status_key = f"{prefix}/status.json"
    status_document = read_json(s3, bucket, status_key)
    restored_status = restore_status_document(status_document)
    if restored_status != status_document:
        put_document(s3, bucket, status_key, restored_status)

    summary = {"schema_version": 1, "run_id": run_id,
        "restored_at": utc_now(), "curated_products": len(product_keys),
        "product_image_manifests": len(image_keys),
        "product_image_failures_moved_to_audit": image_failure_count,
        "review_documents": len(review_keys),
        "changed_review_documents": changed_reviews,
        "status_restored": restored_status != status_document}
    put_json(s3, bucket, f"{prefix}/audit/schema-restore-summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"mode": "dry_run", "network_calls": 0}))
        return
    if not 1 <= args.workers <= 32:
        raise ValueError("workers must be between 1 and 32")
    s3 = boto3.client("s3", config=Config(connect_timeout=5, read_timeout=60,
        max_pool_connections=args.workers * 2,
        retries={"mode": "standard", "total_max_attempts": 5}))
    result = restore_run(s3, args.bucket, args.run_id, args.workers)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
