"""Small Lambda handlers shared by the data-pipeline orchestration adapters."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

import boto3

from .human_review import receive_approval, request_review


class ContractError(ValueError):
    """Raised when an execution input does not satisfy the run contract."""


class StageNotEnabledError(RuntimeError):
    """Raised by a placeholder adapter for a stage whose runtime is not implemented yet."""


NOT_ENABLED_STAGES = {"validate_import", "jev"}


def _contract(event: dict[str, Any]) -> dict[str, Any]:
    required = ("schema_version", "run_mode", "run_id", "input_manifest_sha256", "s3")
    missing = [key for key in required if key not in event]
    if missing:
        raise ContractError(f"missing run contract fields: {', '.join(missing)}")
    if event["schema_version"] != 1:
        raise ContractError("unsupported run contract schema_version")
    if event["run_mode"] not in {"incremental", "full", "integrity", "retry"}:
        raise ContractError("run_mode must be incremental, integrity, full, or retry")
    run_id = event["run_id"]
    digest = event["input_manifest_sha256"]
    if not isinstance(run_id, str) or not run_id or not all(c.isalnum() or c == "-" for c in run_id):
        raise ContractError("run_id must contain only letters, numbers, and hyphens")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ContractError("input_manifest_sha256 must be a lowercase SHA-256 digest")
    s3 = event["s3"]
    if not isinstance(s3, dict) or not s3.get("bucket") or not s3.get("prefix"):
        raise ContractError("s3.bucket and s3.prefix are required")
    if not str(s3["prefix"]).endswith(run_id):
        raise ContractError("s3.prefix must end with run_id")
    return event


def _read_bytes(client: Any, bucket: str, key: str) -> bytes:
    response = client.get_object(Bucket=bucket, Key=key)
    body = response["Body"]
    try:
        return body.read()
    finally:
        close = getattr(body, "close", None)
        if close:
            close()


def _validate_baseline(manifest: bytes) -> dict[str, Any]:
    try:
        document = json.loads(manifest)
        products = document["products"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise ContractError("baseline manifest must contain products") from error
    if not isinstance(products, list) or not products:
        raise ContractError("baseline manifest products must be a non-empty list")
    identifiers: set[str] = set()
    for product in products:
        identifier = str(product.get("product_id", "")) if isinstance(product, dict) else ""
        if not identifier.isdigit() or identifier in identifiers:
            raise ContractError("baseline manifest has an invalid or duplicate product_id")
        identifiers.add(identifier)
    return document


def _checkpoint(client: Any, bucket: str, key: str, baseline_digest: str) -> dict[str, Any]:
    try:
        document = json.loads(_read_bytes(client, bucket, key))
    except client.exceptions.NoSuchKey:
        return {"key": key, "last_successful_run_id": None, "baseline_manifest_sha256": baseline_digest}
    if document.get("baseline_manifest_sha256") != baseline_digest:
        raise ContractError("checkpoint belongs to a different baseline manifest")
    return {
        "key": key,
        "last_successful_run_id": document.get("last_successful_run_id"),
        "baseline_manifest_sha256": baseline_digest,
    }


def initialize_run(event: dict[str, Any], s3: Any | None = None) -> dict[str, Any]:
    """Create an incremental, integrity, or explicitly approved full-run contract."""
    mode = event.get("run_mode")
    if mode not in {"incremental", "integrity", "full"}:
        raise ContractError("initialization requires run_mode incremental, integrity, or full")
    if mode == "full" and event.get("manual_approved") is not True:
        raise ContractError("full collection requires manual_approved=true")
    bucket = event.get("bucket") or os.environ.get("PIPELINE_BUCKET")
    manifest_key = (
        event.get("baseline_manifest_key")
        or event.get("manifest_key")
        or os.environ.get("PIPELINE_BASELINE_MANIFEST_KEY")
        or os.environ.get("PIPELINE_MANIFEST_KEY")
    )
    if not bucket or not manifest_key:
        raise ContractError("PIPELINE_BUCKET and PIPELINE_BASELINE_MANIFEST_KEY are required")
    client = s3 or _s3()
    manifest = _read_bytes(client, bucket, manifest_key)
    baseline = _validate_baseline(manifest)
    digest = hashlib.sha256(manifest).hexdigest()
    prefix_name = "integrity" if mode == "integrity" else "collection"
    run_id = f"{prefix_name}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    prefix = f"pipeline/runs/{run_id}"
    stages = {
        name: {
            "status_key": f"{prefix}/status/{name}.json",
            "success_marker": f"{prefix}/{folder}/{marker}",
        }
        for name, folder, marker in (
            ("crawler", "crawler", "report.json"),
            ("validate", "validate", "report.json"),
            ("import", "import", "report.json"),
            ("jev", "jev", "_SUCCESS.json"),
            ("fashion_clip", "fashion-clip", "report.json"),
            ("integrity", "integrity", "report.json"),
        )
    }
    contract = {
        "schema_version": 1,
        "run_mode": mode,
        "run_id": run_id,
        "input_manifest_sha256": digest,
        "s3": {"bucket": bucket, "prefix": prefix},
        "stages": stages,
        "baseline": {
            "manifest_key": manifest_key,
            "manifest_sha256": digest,
            "product_count": len(baseline["products"]),
        },
    }
    if mode == "incremental":
        checkpoint_key = event.get("checkpoint_key") or os.environ.get(
            "PIPELINE_INCREMENTAL_CHECKPOINT_KEY", "pipeline/state/incremental.json"
        )
        contract["checkpoint"] = _checkpoint(client, bucket, checkpoint_key, digest)
    return contract


def _s3() -> Any:
    return boto3.client("s3", region_name=os.environ.get("AWS_REGION"))


def _status_key(event: dict[str, Any]) -> str:
    return f"{event['s3']['prefix'].rstrip('/')}/status/{event['status']}.json"


def write_status(event: dict[str, Any], s3: Any | None = None) -> dict[str, Any]:
    _contract(event)
    status = event.get("status")
    if status not in {"RUNNING", "SUCCEEDED", "FAILED"}:
        raise ContractError("status must be RUNNING, SUCCEEDED, or FAILED")
    document = {
        "schema_version": 1,
        "run_id": event["run_id"],
        "input_manifest_sha256": event["input_manifest_sha256"],
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if event.get("failure") is not None:
        document["failure"] = event["failure"]
    body = json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    client = s3 or _s3()
    client.put_object(
        Bucket=event["s3"]["bucket"],
        Key=_status_key(event),
        Body=body,
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )
    return document


def stage_not_enabled(event: dict[str, Any], stage: str) -> dict[str, Any]:
    """Fail closed: stop the run before a stage without a runtime can report success."""
    if stage not in NOT_ENABLED_STAGES:
        raise ContractError(f"PIPELINE_STAGE_NAME must be one of {', '.join(sorted(NOT_ENABLED_STAGES))}")
    run_id = event.get("run_id", "unknown") if isinstance(event, dict) else "unknown"
    raise StageNotEnabledError(f"{stage} adapter is not enabled for run {run_id}; no data was changed")


def lambda_handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    action = os.environ.get("ORCHESTRATION_ACTION", "").strip()
    if action == "not_enabled":
        return stage_not_enabled(event, os.environ.get("PIPELINE_STAGE_NAME", "").strip())
    if action == "initialize_run":
        return initialize_run(event)
    if action == "status_writer":
        return write_status(event)
    if action == "review_requester":
        topic_arn = os.environ.get("REVIEW_TOPIC_ARN", "").strip()
        sns = boto3.client("sns", region_name=os.environ.get("AWS_REGION")) if topic_arn else None
        return request_review(event, _s3(), sns, topic_arn)
    if action == "approval_receiver":
        sfn = boto3.client("stepfunctions", region_name=os.environ.get("AWS_REGION"))
        return receive_approval(event, _s3(), sfn, os.environ.get("PIPELINE_BUCKET", "").strip())
    raise ContractError(
        "ORCHESTRATION_ACTION must be initialize_run, status_writer, review_requester, approval_receiver, or not_enabled"
    )
