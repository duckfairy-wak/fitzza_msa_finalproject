"""Manually authorized, bounded raw collection with S3 checkpoint recovery.

No Jev, embeddings or Qdrant operations occur here. A batch is not a finished dataset.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

import boto3
from botocore.config import Config


CHECKPOINT_RESTORE_WORKERS = 16


def safe_checkpoint_path(relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative or ":" in relative:
        raise ValueError("Unsafe checkpoint path")
    if not path.parts or path.parts[0] != "data" or path.suffix != ".json":
        raise ValueError("Checkpoint must be data JSON")
    return Path(*path.parts)


def restore_checkpoints(s3, bucket, prefix):
    try:
        response = s3.get_object(Bucket=bucket, Key=f"{prefix}/crawler/checkpoints.json")
    except s3.exceptions.NoSuchKey:
        return {}, None
    with response["Body"] as body:
        record = json.load(body)
    files = record["files"]
    entries = []
    for relative, digest in files.items():
        path = safe_checkpoint_path(relative)
        if not re.fullmatch("[a-f0-9]{64}", digest):
            raise ValueError("Invalid checkpoint hash")
        entries.append((relative, digest, path))

    def restore_one(entry):
        relative, digest, path = entry
        result = s3.get_object(
            Bucket=bucket,
            Key=f"{prefix}/crawler/objects/{digest}",
        )
        with result["Body"] as body:
            data = body.read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Checkpoint hash mismatch")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return relative

    total = len(entries)
    print(f"checkpoint restore: total={total} workers={CHECKPOINT_RESTORE_WORKERS}",
          flush=True)
    with ThreadPoolExecutor(max_workers=CHECKPOINT_RESTORE_WORKERS) as executor:
        futures = [executor.submit(restore_one, entry) for entry in entries]
        for completed, future in enumerate(as_completed(futures), 1):
            future.result()
            if completed % 500 == 0 or completed == total:
                print(f"checkpoint restore: {completed}/{total}", flush=True)
    return files, response["ETag"]


def save_checkpoints(s3, bucket, prefix, previous, etag):
    files = {}
    for path in sorted(Path("data").rglob("*.json")):
        if path.is_symlink():
            raise ValueError("Checkpoint symlinks are not allowed")
        relative = path.as_posix()
        safe_checkpoint_path(relative)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if previous.get(relative) != digest:
            s3.upload_file(str(path), bucket, f"{prefix}/crawler/objects/{digest}")
        files[relative] = digest
    guard = {"IfMatch": etag} if etag else {"IfNoneMatch": "*"}
    response = s3.put_object(Bucket=bucket, Key=f"{prefix}/crawler/checkpoints.json",
        Body=json.dumps({"files": files, "approved_for_indexing": False}).encode("utf-8"),
        ContentType="application/json", **guard)
    return files, response["ETag"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--category", choices=["상의", "하의", "신발", "아우터", "모자"], required=True)
    parser.add_argument("--stage", choices=["discover", "screen"], required=True)
    parser.add_argument("--max-new", type=int, default=20)
    parser.add_argument("--execute-approved-run", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", args.run_id) or not 1 <= args.max_new <= 100:
        raise ValueError("Invalid run ID or batch size")
    if not args.execute_approved_run:
        print(json.dumps({"mode": "deployment_only", "network_calls": 0,
                          "stage": args.stage, "run_id": args.run_id}))
        return
    s3 = boto3.client("s3", config=Config(connect_timeout=5, read_timeout=30,
        retries={"mode": "standard", "total_max_attempts": 3}))
    prefix = f"pipeline/runs/{args.run_id}"
    files, etag = restore_checkpoints(s3, args.bucket, prefix)
    seed = Path("seed-manifest.json").resolve()
    s3.download_file(args.bucket, f"{prefix}/seed/manifest.json", str(seed))
    os.environ["SEED_MANIFEST"] = str(seed)
    # Checkpoints are published only after every referenced object is safely uploaded.
    try:
        if args.stage == "discover":
            subprocess.run([sys.executable, "-m", "src.cli", "discover", "--category", args.category],
                           check=True, timeout=900)
        else:
            for offset in range(0, args.max_new, 5):
                subprocess.run([sys.executable, "-m", "src.cli", "screen", "--category", args.category,
                    "--max-new", str(min(5, args.max_new - offset)), "--chunk-size", "5", "--delay", "0.8"],
                    check=True, timeout=600)
                files, etag = save_checkpoints(s3, args.bucket, prefix, files, etag)
    finally:
        save_checkpoints(s3, args.bucket, prefix, files, etag)
    print(json.dumps({"status": "raw_batch_finished", "approved_for_indexing": False}))


if __name__ == "__main__":
    main()
