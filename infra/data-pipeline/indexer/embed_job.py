"""Embed a human-approved bundle with FashionCLIP and write vectors to S3 only.

Deployment mode makes no network calls. With --execute-approved-run it:
1. downloads approved/bundle.tar.gz, re-verifies the color approval and checks every product
   against curated/manifest.json (the same files loaded into the product DB),
2. plans one point per product + color + stored evidence image (S3 images/products copy),
3. embeds part by part on CPU and writes each part create-only under pipeline/vector-runs/<id>/,
   so a restarted Job skips finished parts,
4. writes report.json. It never connects to Qdrant.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import re
import time

from entrypoint import unpack_bundle
from review_gate import verify
from vector_points import (invalid_vector_reason, part_name, partition, plan_digest,
                           plan_product_points, verify_bundle_against_manifest)

MODEL_NAME = "patrickjohncyh/fashion-clip"
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
BATCH_SIZE = 16


def read_json(s3, bucket: str, key: str) -> dict:
    with s3.get_object(Bucket=bucket, Key=key)["Body"] as body:
        return json.loads(body.read())


def put_json(s3, bucket: str, key: str, value: object, create_only: bool = False) -> None:
    extra = {"IfNoneMatch": "*"} if create_only else {}
    s3.put_object(Bucket=bucket, Key=key, ContentType="application/json", ServerSideEncryption="AES256",
                  Body=(json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8"), **extra)


def list_keys(s3, bucket: str, prefix: str) -> set[str]:
    keys = set()
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        keys.update(item["Key"] for item in page.get("Contents", []))
    return keys


def image_manifest(s3, bucket: str, key: str, stored: set[str]) -> dict | None:
    # Missing objects return 403 without list permission, so check the listing instead of catching.
    return read_json(s3, bucket, key) if key in stored else None


def load_image(s3, bucket: str, point: dict):
    from PIL import Image

    with s3.get_object(Bucket=bucket, Key=point["image_key"])["Body"] as body:
        data = body.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image_too_large")
    if point.get("image_sha256") and hashlib.sha256(data).hexdigest() != point["image_sha256"]:
        raise ValueError("image_sha256_mismatch")
    with Image.open(BytesIO(data)) as image:
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError("image_too_many_pixels")
        return image.convert("RGB")


class FashionClip:
    """Same preprocessing and feature extraction as recommendation-service SearchEngine.encode_image."""

    def __init__(self, revision: str, threads: int):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        torch.set_num_threads(threads)
        self.torch = torch
        self.model = CLIPModel.from_pretrained(MODEL_NAME, revision=revision).eval()
        self.processor = CLIPProcessor.from_pretrained(MODEL_NAME, revision=revision)

    def encode(self, images: list) -> list[list[float]]:
        inputs = self.processor(images=images, return_tensors="pt")
        with self.torch.no_grad():
            feats = self.model.get_image_features(**inputs)
            if hasattr(feats, "pooler_output") and feats.pooler_output is not None:
                feats = feats.pooler_output
            elif hasattr(feats, "last_hidden_state"):
                feats = feats.last_hidden_state[:, 0, :]
            feats = feats / feats.norm(p=2, dim=-1, keepdim=True).clamp_min(1e-12)
        return feats.cpu().tolist()


def embed_part(s3, bucket: str, model: FashionClip, part: list[dict], revision: str) -> tuple[list[dict], list[dict]]:
    records, failures = [], []
    for start in range(0, len(part), BATCH_SIZE):
        batch, images = [], []
        for point in part[start:start + BATCH_SIZE]:
            try:
                images.append(load_image(s3, bucket, point))
                batch.append(point)
            except Exception as error:  # one bad image must not stop the run
                reason = str(error) if str(error).startswith("image_") else f"image_unreadable:{type(error).__name__}"
                failures.append({"point_id": point["point_id"], "product_id": point["product_id"],
                                 "image_key": point["image_key"], "reason": reason})
        if not batch:
            continue
        try:
            vectors = model.encode(images)
        finally:
            for image in images:
                image.close()
        for point, vector in zip(batch, vectors):
            reason = invalid_vector_reason(vector)
            if reason:
                failures.append({"point_id": point["point_id"], "product_id": point["product_id"],
                                 "image_key": point["image_key"], "reason": reason})
                continue
            records.append({"point_id": point["point_id"], "product_id": point["product_id"],
                            "image_key": point["image_key"], "vector": vector,
                            "payload": point["payload"], "model_revision": revision})
    return records, failures


def run(args) -> dict:
    import boto3
    from botocore.config import Config

    s3 = boto3.client("s3", config=Config(connect_timeout=5, read_timeout=60,
                                          retries={"mode": "standard", "total_max_attempts": 5}))
    run_prefix = f"pipeline/runs/{args.run_id}"
    vector_prefix = f"pipeline/vector-runs/{args.vector_run_id}"
    work = Path(os.environ.get("WORK_DIR", "/work"))
    archive, bundle = work / "approved.tar.gz", work / "approved"
    s3.download_file(args.bucket, f"{run_prefix}/approved/bundle.tar.gz", str(archive))
    bundle_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    unpack_bundle(archive, bundle)
    verify(bundle)
    with s3.get_object(Bucket=args.bucket, Key=f"{run_prefix}/curated/manifest.json")["Body"] as body:
        manifest_bytes = body.read()
    manifest = json.loads(manifest_bytes)
    products = verify_bundle_against_manifest(bundle / "data", manifest)
    color_map = json.loads((bundle / "config/color_map.json").read_text(encoding="utf-8"))

    image_prefix = f"{run_prefix}/images/products/"
    stored_manifests = {key for key in list_keys(s3, args.bucket, image_prefix) if key.endswith("/manifest.json")}
    points, planning_failures, duplicates = [], [], 0
    for product_id, relative in sorted(products.items(), key=lambda item: int(item[0])):
        product = json.loads((bundle / "data" / relative).read_text(encoding="utf-8"))
        planned, failed, duplicate = plan_product_points(
            product, color_map,
            image_manifest(s3, args.bucket, f"{image_prefix}{product_id}/manifest.json", stored_manifests))
        points += planned
        planning_failures += failed
        duplicates += duplicate
    parts = partition(points, args.part_size)
    digest = plan_digest(parts, args.model_revision)
    plan = {"schema_version": 1, "run_id": args.run_id, "vector_run_id": args.vector_run_id,
            "plan_sha256": digest, "model_revision": args.model_revision,
            "approved_bundle_sha256": bundle_sha256, "point_count": len(points), "part_count": len(parts),
            "part_size": args.part_size}
    print(json.dumps({"status": "planned", **plan, "planning_failures": len(planning_failures),
                      "duplicate_point_count": duplicates}), flush=True)

    existing = list_keys(s3, args.bucket, f"{vector_prefix}/")
    if f"{vector_prefix}/plan.json" in existing:
        previous = read_json(s3, args.bucket, f"{vector_prefix}/plan.json")
        if previous.get("plan_sha256") != digest:
            raise ValueError("Existing vector run was planned from different data; use a new --vector-run-id")
    else:
        put_json(s3, args.bucket, f"{vector_prefix}/plan.json", plan, create_only=True)
        put_json(s3, args.bucket, f"{vector_prefix}/failures/planning.json", planning_failures)

    model = FashionClip(args.model_revision, args.threads)
    started = time.time()
    for index, part in enumerate(parts):
        name = part_name(index)
        part_key, summary_key = f"{vector_prefix}/embeddings/{name}", f"{vector_prefix}/parts/{name}.json"
        if part_key in existing and summary_key in existing:
            continue
        records, failures = embed_part(s3, args.bucket, model, part, args.model_revision)
        # Summary first: a crash before the part write re-embeds this part on restart.
        put_json(s3, args.bucket, summary_key, {"part": name, "planned": len(part),
                                                 "written": len(records), "failures": failures})
        body = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records).encode("utf-8")
        s3.put_object(Bucket=args.bucket, Key=part_key, Body=body, ContentType="application/x-ndjson",
                      ServerSideEncryption="AES256", IfNoneMatch="*")
        print(json.dumps({"status": "part_written", "part": name, "index": index + 1, "parts": len(parts),
                          "written": len(records), "failed": len(failures),
                          "elapsed_seconds": round(time.time() - started)}), flush=True)

    written, embed_failures = 0, Counter()
    for index in range(len(parts)):
        summary = read_json(s3, args.bucket, f"{vector_prefix}/parts/{part_name(index)}.json")
        written += summary["written"]
        embed_failures.update(failure["reason"] for failure in summary["failures"])
    report = {**plan, "status": "embedded", "input_embedding_count": written,
              "duplicate_point_count": duplicates,
              "planning_failures_by_reason": dict(Counter(item["reason"] for item in planning_failures)),
              "embedding_failures_by_reason": dict(embed_failures),
              "invalid_vector_count": sum(count for reason, count in embed_failures.items()
                                          if not reason.startswith("image_")),
              "source_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()}
    put_json(s3, args.bucket, f"{vector_prefix}/report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--vector-run-id", required=True)
    parser.add_argument("--model-revision", required=True, help="40-character Hugging Face commit SHA")
    parser.add_argument("--part-size", type=int, default=256)
    parser.add_argument("--threads", type=int, default=int(os.environ.get("EMBED_THREADS", "1")))
    parser.add_argument("--execute-approved-run", action="store_true")
    args = parser.parse_args()
    for value in (args.run_id, args.vector_run_id):
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", value):
            raise ValueError("Invalid run ID")
    if not re.fullmatch(r"[a-f0-9]{40}", args.model_revision):
        raise ValueError("Model revision must be a 40-character commit SHA")
    if not 1 <= args.part_size <= 1000:
        raise ValueError("Invalid part size")
    if not args.execute_approved_run:
        print(json.dumps({"mode": "deployment_only", "network_calls": 0, "embedding": False}))
        return
    print(json.dumps(run(args), ensure_ascii=False))


if __name__ == "__main__":
    main()
