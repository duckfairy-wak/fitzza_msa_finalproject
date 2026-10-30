"""Load an embedded vector run from S3 into a new versioned Qdrant collection and validate it.

Deployment mode makes no network calls. With --execute-approved-run it:
1. reads report.json and every embeddings/part-*.jsonl of the vector run and rejects the run
   before touching Qdrant if any vector, payload or model revision is invalid,
2. with --exclude-unsellable-colors, re-reads the approved bundle the run embedded (SHA-256 must
   match report.json) and drops points whose color is not a sellable option, using the same rule
   as the embedding plan; vectors are reused, so a run embedded before that rule needs no re-embedding,
3. creates fitzza_products_<version> (512, Cosine) with payload indexes, or resumes it with --resume,
4. upserts in batches with wait=true and exponential backoff, recording failed batches,
5. validates counts, payloads, filters and search, then writes import-report-<collection>.json.
It never changes an alias or touches any other collection.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import random
import re
import sys
import time

from vector_points import (PAYLOAD_INDEXES, VECTOR_SIZE, color_key, invalid_vector_reason, part_name,
                           payload_problems, sellable_color_keys)

COLLECTION_PATTERN = r"fitzza_products_[a-z0-9_]{1,48}"


def read_json(s3, bucket: str, key: str) -> dict:
    with s3.get_object(Bucket=bucket, Key=key)["Body"] as body:
        return json.loads(body.read())


def load_records(s3, bucket: str, prefix: str, report: dict) -> tuple[list[dict], dict]:
    records, problems, seen = [], Counter(), set()
    for index in range(report["part_count"]):
        with s3.get_object(Bucket=bucket, Key=f"{prefix}/embeddings/{part_name(index)}")["Body"] as body:
            lines = body.read().decode("utf-8").splitlines()
        for line in lines:
            if not line.strip():
                continue
            record = json.loads(line)
            if record["point_id"] in seen:
                problems["duplicate_point"] += 1
                continue
            seen.add(record["point_id"])
            if record.get("model_revision") != report["model_revision"]:
                problems["model_revision_mismatch"] += 1
            reason = invalid_vector_reason(record.get("vector"))
            if reason:
                problems[f"invalid_vector:{reason}"] += 1
            for problem in payload_problems(record.get("payload") or {}):
                problems[f"payload:{problem}"] += 1
            records.append(record)
    return records, dict(problems)


def approved_sellable_keys(s3, bucket: str, report: dict) -> dict[int, set[str]]:
    """product_id -> sellable color keys, read from the exact approved bundle the run embedded."""
    from entrypoint import unpack_bundle

    work = Path(os.environ.get("WORK_DIR", "/work"))
    archive, bundle = work / "approved-for-import.tar.gz", work / "approved-for-import"
    s3.download_file(bucket, f"pipeline/runs/{report['run_id']}/approved/bundle.tar.gz", str(archive))
    if hashlib.sha256(archive.read_bytes()).hexdigest() != report["approved_bundle_sha256"]:
        raise ValueError("Approved bundle differs from the one this vector run embedded")
    unpack_bundle(archive, bundle)
    keys = {}
    for path in sorted((bundle / "data").rglob("*.json")):
        product = json.loads(path.read_text(encoding="utf-8"))
        keys[int(product["product_id"])] = sellable_color_keys(product)
    return keys


def exclude_unsellable(records: list[dict], keys: dict[int, set[str]]) -> tuple[list[dict], list[dict]]:
    kept, excluded = [], []
    for record in records:
        product_id = int(record["product_id"])
        if product_id not in keys:
            raise ValueError(f"Product {product_id} is not in the approved bundle")
        raw = record["payload"]["color_raw"]
        if color_key(raw) in keys[product_id]:
            kept.append(record)
        else:
            excluded.append({"point_id": record["point_id"], "product_id": product_id, "color_raw": raw,
                             "image_key": record.get("image_key")})
    return kept, excluded


def upsert_with_retry(client, models, collection: str, batch: list[dict], attempts: int = 5) -> None:
    points = [models.PointStruct(id=record["point_id"], vector=record["vector"], payload=record["payload"])
              for record in batch]
    for attempt in range(attempts):
        try:
            client.upsert(collection_name=collection, points=points, wait=True)
            return
        except Exception:
            if attempt + 1 == attempts:
                raise
            time.sleep(min(30, 2 ** attempt))


def prepare_collection(client, models, collection: str, resume: bool) -> None:
    if client.collection_exists(collection):
        if not resume:
            raise ValueError(f"{collection} already exists; pass --resume to continue the same import")
    else:
        client.create_collection(collection_name=collection,
                                 vectors_config=models.VectorParams(size=VECTOR_SIZE, distance=models.Distance.COSINE))
    schemas = {"integer": models.PayloadSchemaType.INTEGER, "keyword": models.PayloadSchemaType.KEYWORD}
    for field, kind in PAYLOAD_INDEXES.items():
        client.create_payload_index(collection_name=collection, field_name=field,
                                    field_schema=schemas[kind], wait=True)


def validate_collection(client, models, collection: str, records: list[dict]) -> dict:
    info = client.get_collection(collection)
    vectors = info.config.params.vectors
    checks = {"status_green": str(info.status).lower().endswith("green"),
              "vector_size_512": vectors.size == VECTOR_SIZE,
              "distance_cosine": str(vectors.distance).lower().endswith("cosine")}
    count = client.count(collection_name=collection, exact=True).count
    checks["point_count_matches"] = count == len(records)
    sampler = random.Random(20261025)
    product_ids = sorted({record["product_id"] for record in records})
    sampled_products = sampler.sample(product_ids, min(10, len(product_ids)))
    checks["product_filter_hits"] = all(client.count(
        collection_name=collection, exact=True,
        count_filter=models.Filter(must=[models.FieldCondition(
            key="product_id", match=models.MatchValue(value=product_id))])).count > 0
        for product_id in sampled_products)
    samples = sampler.sample(records, min(20, len(records)))
    stored = {str(point.id): point.payload for point in client.retrieve(
        collection_name=collection, ids=[record["point_id"] for record in samples], with_payload=True)}
    checks["sample_payload_matches"] = all(
        stored.get(record["point_id"], {}).get(key) == record["payload"][key]
        for record in samples for key in ("product_id", "color_variant", "normalized_color", "image_key"))
    hits = client.query_points(collection_name=collection, query=samples[0]["vector"], limit=5,
                               with_payload=True).points if samples else []
    checks["sample_search_returns_payload"] = bool(hits) and all(hit.payload for hit in hits)
    color = samples[0]["payload"]["normalized_color"] if samples else "black"
    checks["color_filter_hits"] = client.count(
        collection_name=collection, exact=True,
        count_filter=models.Filter(must=[models.FieldCondition(
            key="color_normalized", match=models.MatchValue(value=color))])).count > 0
    return {"qdrant_point_count": count, "checks": checks}


def run(args) -> dict:
    import boto3
    from botocore.config import Config
    from qdrant_client import QdrantClient, models

    s3 = boto3.client("s3", config=Config(connect_timeout=5, read_timeout=60,
                                          retries={"mode": "standard", "total_max_attempts": 5}))
    prefix = f"pipeline/vector-runs/{args.vector_run_id}"
    report = read_json(s3, args.bucket, f"{prefix}/report.json")
    if report.get("status") != "embedded":
        raise ValueError("Vector run is not finished")
    records, problems = load_records(s3, args.bucket, prefix, report)
    result = {"vector_run_id": args.vector_run_id, "collection_name": args.collection,
              "model_revision": report["model_revision"],
              "approved_bundle_sha256": report["approved_bundle_sha256"],
              "input_embedding_count": len(records), "embedded_count_in_report": report["input_embedding_count"],
              "record_problems": problems, "upsert_attempt_count": 0, "upsert_success_count": 0,
              "failed_batch_count": 0, "failed_point_ids": []}
    if problems or len(records) != report["input_embedding_count"]:
        result.update(status="rejected_before_qdrant", passed=False)
        return result
    excluded = []
    if getattr(args, "exclude_unsellable_colors", False):
        loaded_products = {r["product_id"] for r in records}
        records, excluded = exclude_unsellable(records, approved_sellable_keys(s3, args.bucket, report))
        result["sellable_filter"] = {
            "excluded_point_count": len(excluded),
            "products_with_excluded_points": len({item["product_id"] for item in excluded}),
            "products_without_points_after_filter": sorted(loaded_products - {r["product_id"] for r in records}),
            "excluded_points": excluded}
    result.update(import_point_count=len(records),
                  color_distribution=dict(Counter(r["payload"]["normalized_color"] for r in records)),
                  category_distribution=dict(Counter(r["payload"]["category"] for r in records)),
                  product_count=len({r["product_id"] for r in records}))
    print(json.dumps({"status": "planned_import", "import_point_count": len(records),
                      "excluded_unsellable": len(excluded)}), flush=True)

    client = QdrantClient(url=os.environ["QDRANT_URL"], timeout=60)
    prepare_collection(client, models, args.collection, args.resume)
    for start in range(0, len(records), args.batch_size):
        batch = records[start:start + args.batch_size]
        result["upsert_attempt_count"] += len(batch)
        try:
            upsert_with_retry(client, models, args.collection, batch)
            result["upsert_success_count"] += len(batch)
        except Exception as error:
            result["failed_batch_count"] += 1
            result["failed_point_ids"] += [record["point_id"] for record in batch]
            print(json.dumps({"status": "batch_failed", "start": start, "error": type(error).__name__}), flush=True)
        if (start // args.batch_size) % 10 == 0:
            print(json.dumps({"status": "upserting", "done": start + len(batch), "total": len(records)}), flush=True)
    result.update(validate_collection(client, models, args.collection, records))
    if excluded:
        ids = [item["point_id"] for item in excluded]
        present = [point for start in range(0, len(ids), 256)
                   for point in client.retrieve(collection_name=args.collection, ids=ids[start:start + 256])]
        result["checks"]["unsellable_points_absent"] = not present
    result["passed"] = (result["failed_batch_count"] == 0
                        and result["upsert_success_count"] == len(records)
                        and all(result["checks"].values()))
    result["status"] = "validated" if result["passed"] else "validation_failed"
    result["validated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    s3.put_object(Bucket=args.bucket, Key=f"{prefix}/import-report-{args.collection}.json",
                  Body=(json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                  ContentType="application/json", ServerSideEncryption="AES256")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--vector-run-id", required=True)
    parser.add_argument("--collection", required=True, help="new version collection, e.g. fitzza_products_20261025_01")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--resume", action="store_true", help="continue into a collection this run already created")
    parser.add_argument("--exclude-unsellable-colors", action="store_true",
                        help="drop points whose color is not an active option in the approved bundle")
    parser.add_argument("--execute-approved-run", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", args.vector_run_id):
        raise ValueError("Invalid vector run ID")
    if not re.fullmatch(COLLECTION_PATTERN, args.collection) or args.collection.endswith("_current"):
        raise ValueError("Collection must be a new fitzza_products_<version> name, never an alias")
    if not 100 <= args.batch_size <= 500:
        raise ValueError("Batch size must be 100-500")
    if not args.execute_approved_run:
        print(json.dumps({"mode": "deployment_only", "network_calls": 0, "qdrant_writes": 0}))
        return
    result = run(args)
    print(json.dumps(result, ensure_ascii=False))
    if not result["passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
