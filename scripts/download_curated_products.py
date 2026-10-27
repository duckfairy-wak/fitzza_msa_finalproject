"""Download collection curated products (+ optional images inventory) from S3.

Requires AWS credentials (``--profile fitzza`` by default). Writes under
``.data/<run-id>/`` and never commits those files.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError, ProfileNotFound


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUCKET = "fitzza-prod-foundation-databucket-wwng6wfc0hqy"
DEFAULT_RUN_ID = "collection-20261025-01"
DEFAULT_REGION = "ap-northeast-2"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download curated product run artifacts from S3.")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--profile", default="fitzza")
    parser.add_argument(
        "--output",
        type=Path,
        help="destination root (default: .data/<run-id>)",
    )
    parser.add_argument(
        "--include-images",
        action="store_true",
        help="also sync images/products (large: ~28k objects)",
    )
    parser.add_argument(
        "--include-image-failures",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="download image-download-failures audit (default: on)",
    )
    return parser


def download_prefix(client, bucket: str, prefix: str, destination: Path) -> int:
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents") or []:
            key = item["Key"]
            if key.endswith("/"):
                continue
            relative = key[len(prefix) :] if key.startswith(prefix) else Path(key).name
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(bucket, key, str(target))
            count += 1
    return count


def download_key(client, bucket: str, key: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    client.download_file(bucket, key, str(destination))


def main() -> int:
    args = build_parser().parse_args()
    run_prefix = f"pipeline/runs/{args.run_id}"
    output = args.output or (ROOT / ".data" / args.run_id)

    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        client = session.client("s3")
        download_key(client, args.bucket, f"{run_prefix}/status.json", output / "status.json")
        curated_count = download_prefix(
            client, args.bucket, f"{run_prefix}/curated/", output / "curated"
        )
        failure_count = 0
        if args.include_image_failures:
            failure_count = download_prefix(
                client,
                args.bucket,
                f"{run_prefix}/audit/image-download-failures/products/",
                output / "audit" / "image-download-failures" / "products",
            )
        image_count = 0
        if args.include_images:
            image_count = download_prefix(
                client,
                args.bucket,
                f"{run_prefix}/images/products/",
                output / "images" / "products",
            )
    except (BotoCoreError, ClientError, ProfileNotFound) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1

    print(
        json.dumps(
            {
                "output": str(output),
                "curated_objects": curated_count,
                "image_failure_objects": failure_count,
                "image_objects": image_count,
                "status": str(output / "status.json"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
