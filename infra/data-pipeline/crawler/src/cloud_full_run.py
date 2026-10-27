"""Run the approved 3000-product collection, images, and reviews entirely on EKS."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

import boto3
from botocore.config import Config

from src.cloud_batch import restore_checkpoints, save_checkpoints
from src.cloud_media import put_json, upload_product_images, upload_reviews, utc_now
from src.collector.config import CATEGORY_CONFIG
from src.collector.screen_until_ready import handled_ids
from src.collector.select_balanced import select_category
from src.curate_dataset import prepare


def status(s3, bucket: str, prefix: str, stage: str, **values) -> None:
    record = {"schema_version": 1, "stage": stage, "state": "running",
              "updated_at": utc_now(), **values}
    put_json(s3, bucket, f"{prefix}/status.json", record)
    print(json.dumps(record, ensure_ascii=False), flush=True)


def run_command(arguments: list[str], timeout: int) -> None:
    subprocess.run([sys.executable, "-u", "-m", *arguments], check=True, timeout=timeout)


def handled_count(category: str) -> int:
    return len(handled_ids(category))


def download_seed(s3, bucket: str, prefix: str) -> tuple[Path, Path]:
    manifest_path = Path("seed-manifest.json").resolve()
    s3.download_file(bucket, f"{prefix}/seed/manifest.json", str(manifest_path))
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    seed_root = Path("seed-data").resolve()
    for record in document["products"]:
        relative = Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".json":
            raise ValueError("unsafe seed path")
        destination = seed_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(bucket, f"{prefix}/seed/objects/{record['sha256']}", str(destination))
        if hashlib.sha256(destination.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("seed object hash mismatch")
    return manifest_path, seed_root


def upload_curated(s3, bucket: str, prefix: str, report: dict,
                   files: dict[str, bytes]) -> dict:
    products = []
    for relative, data in sorted(files.items()):
        product = json.loads(data)
        key = f"{prefix}/curated/{relative}"
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/json",
                      ServerSideEncryption="AES256")
        products.append({"product_id": str(product["product_id"]),
            "category": product["dataset"]["logical_category"], "path": relative[5:],
            "sha256": hashlib.sha256(data).hexdigest(), "s3_key": key})
    manifest = {"schema_version": 1, "status": "pending_quality_and_human_review",
                "unique_product_count": len(products), "products": products,
                "selected_by_category": report["selected_by_category"]}
    put_json(s3, bucket, f"{prefix}/curated/manifest.json", manifest)
    put_json(s3, bucket, f"{prefix}/curated/report.json", report)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--execute-approved-run", action="store_true")
    args = parser.parse_args()
    if not args.execute_approved_run:
        print(json.dumps({"mode": "deployment_only", "network_calls": 0}))
        return
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", args.run_id):
        raise ValueError("invalid run ID")

    s3 = boto3.client("s3", config=Config(connect_timeout=5, read_timeout=60,
        retries={"mode": "standard", "total_max_attempts": 5}))
    prefix = f"pipeline/runs/{args.run_id}"
    manifest_path, seed_root = download_seed(s3, args.bucket, prefix)
    os.environ["SEED_MANIFEST"] = str(manifest_path)
    files, etag = restore_checkpoints(s3, args.bucket, prefix)

    candidate_factor = 18.0
    minimum_candidates = 10_000
    for category in CATEGORY_CONFIG:
        selection = select_category(category)
        if selection["complete"]:
            continue

        complete = False
        status(s3, args.bucket, prefix, "discovery", category=category,
               candidate_factor=candidate_factor,
               minimum_candidates=minimum_candidates)
        run_command(["src.cli", "discover", "--category", category,
                     "--factor", str(candidate_factor), "--min-candidates",
                     str(minimum_candidates), "--page-size", "60",
                     "--max-pages-per-sort", "100"], 3600)
        files, etag = save_checkpoints(s3, args.bucket, prefix, files, etag)

        while True:
            selection = select_category(category)
            status(s3, args.bucket, prefix, "screening", category=category,
                   candidate_factor=candidate_factor,
                   minimum_candidates=minimum_candidates,
                   selected=selection["selected"],
                   target=selection["required"], counts=selection["counts"],
                   deficit=selection["deficit"])
            if selection["complete"]:
                complete = True
                break
            before = handled_count(category)
            run_command(["src.fast_screen", "--category", category,
                         "--max-new", "500", "--workers", "8"], 1800)
            files, etag = save_checkpoints(s3, args.bucket, prefix, files, etag)
            if handled_count(category) == before:
                break
        if not complete:
            selection = select_category(category)
            raise RuntimeError(
                f"{category} quota incomplete after expanded discovery: "
                f"{selection['deficit']}"
            )

    status(s3, args.bucket, prefix, "curation")
    report, curated_files = prepare([seed_root, Path("data/screened")])
    if not report["ready_for_jev"] or report["selected_count"] != 3000:
        raise RuntimeError(f"curation incomplete: {report['deficits']}")
    manifest = upload_curated(s3, args.bucket, prefix, report, curated_files)

    product_by_id = {str(json.loads(data)["product_id"]): json.loads(data)
                     for data in curated_files.values()}
    product_image_count = 0
    for index, record in enumerate(manifest["products"], 1):
        result = upload_product_images(s3, args.bucket, prefix,
                                       product_by_id[record["product_id"]])
        product_image_count += int(result.get("image_count", 0))
        if index % 10 == 0:
            status(s3, args.bucket, prefix, "product-images", completed=index,
                   total=3000, images_this_run=product_image_count)

    review_count = review_image_count = 0
    for index, record in enumerate(manifest["products"], 1):
        result = upload_reviews(s3, args.bucket, prefix, record["product_id"], 100)
        review_count += int(result.get("review_count", 0))
        review_image_count += int(result.get("image_count", 0))
        if index % 10 == 0:
            status(s3, args.bucket, prefix, "reviews-and-images", completed=index,
                   total=3000, reviews_this_run=review_count,
                   images_this_run=review_image_count)

    final = {"schema_version": 1, "stage": "complete", "state": "succeeded",
             "completed_at": utc_now(), "product_count": 3000,
             "product_images_this_run": product_image_count,
             "reviews_this_run": review_count,
             "review_images_this_run": review_image_count}
    put_json(s3, args.bucket, f"{prefix}/status.json", final)
    print(json.dumps(final, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
