"""Explicitly authorized Jev stage; deployment mode never reads the key or calls Jev."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile

MAX_PRODUCTS = 30000
MAX_TOTAL_BYTES = 1024 ** 3
MAX_PRODUCT_BYTES = 2 * 1024 * 1024
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
DOWNLOAD_WORKERS = 8


def read_limited(s3, bucket: str, key: str, limit: int) -> bytes:
    with s3.get_object(Bucket=bucket, Key=key)["Body"] as body:
        data = body.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Object exceeds size limit")
    return data


def object_exists(s3, bucket: str, key: str) -> bool:
    # Without list permission S3 answers a missing GetObject with 403, so check by exact-key listing.
    response = s3.list_objects_v2(Bucket=bucket, Prefix=key, MaxKeys=1)
    return any(item["Key"] == key for item in response.get("Contents", []))


def validated_product_records(manifest: dict, prefix: str) -> list[dict]:
    """Accept only manifest rows that point at this run's curated/data/<category>/<id>.json."""
    records = manifest.get("products") if isinstance(manifest, dict) else None
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_PRODUCTS:
        raise ValueError("Invalid curated manifest product list")
    identifiers, paths = set(), set()
    for record in records:
        identifier = str(record["product_id"])
        relative = record["path"]
        path = PurePosixPath(relative)
        if not re.fullmatch(r"[1-9][0-9]*", identifier) or identifier in identifiers:
            raise ValueError("Invalid or duplicate product ID")
        if (path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative
                or len(path.parts) != 2 or path.parts[0] != record["category"]
                or path.name != f"{identifier}.json" or relative in paths):
            raise ValueError("Unsafe curated product path")
        if record["s3_key"] != f"{prefix}/curated/data/{relative}":
            raise ValueError("Curated product key outside run prefix")
        if not re.fullmatch(r"[a-f0-9]{64}", record["sha256"]):
            raise ValueError("Invalid product digest")
        identifiers.add(identifier)
        paths.add(relative)
    return records


def download_product(s3, bucket: str, record: dict, destination: Path) -> int:
    data = read_limited(s3, bucket, record["s3_key"], MAX_PRODUCT_BYTES)
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise ValueError("Curated product digest mismatch")
    product = json.loads(data)
    if not isinstance(product, dict) or str(product.get("product_id")) != str(record["product_id"]):
        raise ValueError("Curated product identity mismatch")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        output.write(data)
    return len(data)


def download_curated_products(s3, bucket: str, prefix: str, data_root: Path) -> dict:
    """Copy the run's curated product JSON into data_root after verifying each manifest digest."""
    manifest_bytes = read_limited(s3, bucket, f"{prefix}/curated/manifest.json", MAX_MANIFEST_BYTES)
    records = validated_product_records(json.loads(manifest_bytes), prefix)
    total_bytes = 0
    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        futures = [pool.submit(download_product, s3, bucket, record, data_root / record["path"])
                   for record in records]
        try:
            for future in as_completed(futures):
                total_bytes += future.result()
                if total_bytes > MAX_TOTAL_BYTES:
                    raise ValueError("Curated products exceed total size limit")
        except BaseException:
            for pending in futures:
                pending.cancel()
            raise
    return {"input_layout": "manifest", "product_count": len(records),
            "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()}


def extract_curated_bundle(s3, bucket: str, prefix: str, bundle_root: Path) -> dict:
    archive = Path("/work/curated.tar.gz")
    s3.download_file(bucket, f"{prefix}/curated/bundle.tar.gz", str(archive))
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        if len(members) > MAX_PRODUCTS or sum(member.size for member in members) > MAX_TOTAL_BYTES:
            raise ValueError("Curated bundle exceeds limits")
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or ".." in path.parts or "\\" in member.name or ":" in member.name
                    or not (member.isfile() or member.isdir())):
                raise ValueError("Unsafe bundle member")
        source.extractall(bundle_root, members=members, filter="data")
    return {"input_layout": "bundle",
            "product_count": sum(1 for _ in (bundle_root / "data").rglob("*.json"))}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--input-layout", choices=("manifest", "bundle"), default="manifest",
                        help="manifest: curated/manifest.json + curated/data/; bundle: curated/bundle.tar.gz")
    parser.add_argument("--execute-approved-run", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", args.run_id):
        raise ValueError("Invalid run ID")
    if not args.execute_approved_run:
        print(json.dumps({"mode": "deployment_only", "network_calls": 0, "jev_calls": 0}))
        return
    import boto3
    from botocore.config import Config

    config = Config(connect_timeout=5, read_timeout=30,
                    retries={"mode": "standard", "total_max_attempts": 3})
    s3 = boto3.client("s3", config=config)
    ssm = boto3.client("ssm", config=config)
    prefix = f"pipeline/runs/{args.run_id}"
    bundle = Path("/work/review-bundle")
    if args.input_layout == "manifest":
        source = download_curated_products(s3, args.bucket, prefix, bundle / "data")
    else:
        source = extract_curated_bundle(s3, args.bucket, prefix, bundle)
    print(json.dumps({"status": "curated_input_ready", **source}), flush=True)
    output = bundle / "config"
    output.mkdir(parents=True, exist_ok=True)
    results = output / "color_map_jev_results.jsonl"
    results_key = f"{prefix}/jev/{results.name}"
    if object_exists(s3, args.bucket, results_key):
        with s3.get_object(Bucket=args.bucket, Key=results_key)["Body"] as body, \
                results.open("wb") as file:
            shutil.copyfileobj(body, file)
    parameter = ssm.get_parameter(Name="/fitzza/prod/data-pipeline/typesafe-api-key", WithDecryption=True)
    env = dict(os.environ, TYPESAFE_API_KEY=parameter["Parameter"]["Value"])
    try:
        subprocess.run([sys.executable, "/app/jev/scripts/generate_color_map.py",
            "--data", str(bundle / "data"), "--config", str(output), "--workers", "4"],
            env=env, check=True, timeout=1800)
    finally:
        env.pop("TYPESAFE_API_KEY", None)
        parameter.clear()
        if results.exists():
            s3.upload_file(str(results), args.bucket, results_key)
    shutil.copyfile("/app/jev/scripts/color_map_overrides.json", output / "color_map_overrides.json")
    # No approval marker is generated: local human review must happen after this stage.
    review_archive = Path("/work/review-bundle.tar.gz")
    with tarfile.open(review_archive, "w:gz") as target:
        target.add(bundle / "data", arcname="data")
        target.add(output, arcname="config")
    s3.upload_file(str(review_archive), args.bucket, f"{prefix}/jev/review-bundle.tar.gz")
    print(json.dumps({"status": "waiting_for_human_review", "approved_for_indexing": False, **source}))


if __name__ == "__main__":
    main()
