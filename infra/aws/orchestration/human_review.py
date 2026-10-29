"""Human color review between Jev and FashionCLIP: request, notify and resume on approval.

The state machine waits with a Step Functions task token. The token is kept under
orchestration/review/<run-id>/, outside the pipeline/ prefix that pipeline Job roles can read,
so a Job cannot approve its own run. Only an uploaded approved bundle whose approval markers
pass the checks below resumes the run.
"""

from __future__ import annotations

import hashlib
import json
import re
import tarfile
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import unquote_plus

# Keep in sync with TimeoutSeconds of the WaitForHumanReview state.
REVIEW_TIMEOUT_SECONDS = 259200
REVIEW_PREFIX = "orchestration/review"
APPROVED_BUNDLE_KEY = re.compile(r"pipeline/runs/([a-z0-9][a-z0-9-]{2,63})/approved/bundle\.tar\.gz")
APPROVAL_MARKER = "config/_APPROVED.json"
QUALITY_MARKER = "config/_QUALITY_APPROVED.json"
MAX_BUNDLE_BYTES = 1024 ** 3
MAX_MARKER_BYTES = 1024 ** 2
_MODEL_REVISION = re.compile(r"[a-f0-9]{40}")


class ReviewError(ValueError):
    """Raised when a review request or approval event is malformed."""


class BundleRejected(ValueError):
    """Raised when an uploaded bundle does not carry valid human and quality approvals."""


def _put_json(s3: Any, bucket: str, key: str, document: dict[str, Any], create_only: bool = False) -> None:
    extra = {"IfNoneMatch": "*"} if create_only else {}
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="AES256",
        **extra,
    )


def _read_json(s3: Any, bucket: str, key: str) -> dict[str, Any]:
    body = s3.get_object(Bucket=bucket, Key=key)["Body"]
    try:
        return json.loads(body.read())
    finally:
        close = getattr(body, "close", None)
        if close:
            close()


def _error_code(error: Exception) -> str:
    return str((getattr(error, "response", None) or {}).get("Error", {}).get("Code", ""))


def review_message(contract: dict[str, Any], deadline: datetime) -> tuple[str, str]:
    """Return an ASCII subject (SNS email requirement) and the reviewer instructions."""
    run_id = contract["run_id"]
    bucket = contract["s3"]["bucket"]
    prefix = contract["s3"]["prefix"].rstrip("/")
    count = contract.get("review_required_count")
    lines = [
        f"Fitzza 색상 검수 요청: {run_id}",
        "",
        "Jev 색상 정규화가 끝났습니다. 검수와 품질 승인을 마친 승인본을 올리면 FashionCLIP 단계가 이어집니다.",
    ]
    if isinstance(count, int):
        lines.append(f"검수 대상: {count}건")
    lines += [
        f"기한: {deadline.astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M')} KST (지나면 이 실행은 실패로 기록됩니다)",
        "",
        "1) 검수 번들 받기",
        f"   aws s3 cp s3://{bucket}/{prefix}/jev/review-bundle.tar.gz <작업폴더>/ --profile fitzza",
        "2) 검수·승인 (crawler 폴더에서, infra/data-pipeline/DEPLOYMENT.md 참고)",
        "   python -m src.color_review page --bundle <작업폴더>",
        "   python -m src.color_review apply --bundle <작업폴더> --decisions <review_decisions.json>",
        "   python -m src.review_gate approve --bundle <작업폴더>",
        "   (품질 검증 후 config/_QUALITY_APPROVED.json 작성)",
        "   python -m src.color_review package --bundle <작업폴더> --output <최종본.tar.gz> --require-quality",
        "3) 승인본 올리기",
        f"   aws s3 cp <최종본.tar.gz> s3://{bucket}/{prefix}/approved/bundle.tar.gz --profile fitzza",
    ]
    return f"[Fitzza] Color review requested: {run_id}"[:99], "\n".join(lines)


def request_review(
    event: dict[str, Any],
    s3: Any,
    sns: Any | None = None,
    topic_arn: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Store the task token, record the request and notify reviewers when a topic is configured."""
    contract, token = event.get("contract"), event.get("task_token")
    if not isinstance(contract, dict) or not isinstance(token, str) or not token:
        raise ReviewError("review request needs contract and task_token")
    run_id = contract.get("run_id", "")
    bucket = (contract.get("s3") or {}).get("bucket")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,63}", str(run_id)) or not bucket:
        raise ReviewError("review request contract needs a valid run_id and s3.bucket")
    requested_at = now or datetime.now(timezone.utc)
    deadline = requested_at + timedelta(seconds=REVIEW_TIMEOUT_SECONDS)
    base = f"{REVIEW_PREFIX}/{run_id}"
    _put_json(s3, bucket, f"{base}/task-token.json", {"run_id": run_id, "task_token": token})
    request = {
        "schema_version": 1,
        "run_id": run_id,
        "input_manifest_sha256": contract.get("input_manifest_sha256"),
        "review_bundle_key": f"{contract['s3']['prefix'].rstrip('/')}/jev/review-bundle.tar.gz",
        "approved_bundle_key": f"{contract['s3']['prefix'].rstrip('/')}/approved/bundle.tar.gz",
        "requested_at": requested_at.isoformat(),
        "deadline": deadline.isoformat(),
        "notified": bool(topic_arn),
    }
    _put_json(s3, bucket, f"{base}/request.json", request)
    if topic_arn:
        if sns is None:
            raise ReviewError("an SNS client is required when a review topic is configured")
        subject, message = review_message(contract, deadline)
        sns.publish(TopicArn=topic_arn, Subject=subject, Message=message)
    return request


class _HashingReader:
    """File-like wrapper that hashes and bounds every byte tarfile reads."""

    def __init__(self, raw: Any, limit: int):
        self.raw, self.limit = raw, limit
        self.sha256, self.size = hashlib.sha256(), 0

    def read(self, size: int = -1) -> bytes:
        data = self.raw.read() if size is None or size < 0 else self.raw.read(size)
        self.size += len(data)
        if self.size > self.limit:
            raise BundleRejected("approved bundle exceeds the size limit")
        self.sha256.update(data)
        return data


def inspect_bundle(s3: Any, bucket: str, key: str, limit: int = MAX_BUNDLE_BYTES) -> dict[str, Any]:
    """Stream the bundle once: read both approval markers and hash the whole object."""
    body = s3.get_object(Bucket=bucket, Key=key)["Body"]
    reader = _HashingReader(body, limit)
    markers: dict[str, Any] = {}
    try:
        with tarfile.open(fileobj=reader, mode="r|gz") as archive:
            for member in archive:
                if member.name not in (APPROVAL_MARKER, QUALITY_MARKER):
                    continue
                if not member.isfile() or member.size > MAX_MARKER_BYTES or member.name in markers:
                    raise BundleRejected(f"unexpected approval marker entry: {member.name}")
                markers[member.name] = json.loads(archive.extractfile(member).read())
        while reader.read(1024 * 1024):
            pass
    except BundleRejected:
        raise
    except (tarfile.TarError, OSError, EOFError, ValueError, RecursionError) as error:
        raise BundleRejected(f"approved bundle is not a readable tar.gz with JSON markers: {error}") from error
    finally:
        close = getattr(body, "close", None)
        if close:
            close()
    approval, quality = markers.get(APPROVAL_MARKER), markers.get(QUALITY_MARKER)
    if not isinstance(approval, dict) or approval.get("human_color_review_approved") is not True:
        raise BundleRejected("human color approval (config/_APPROVED.json) is missing or not approved")
    if not isinstance(quality, dict) or quality.get("approved") is not True:
        raise BundleRejected("dataset quality approval (config/_QUALITY_APPROVED.json) is missing or not approved")
    files = approval.get("files")
    if not isinstance(files, dict) or not files or quality.get("files") != files:
        raise BundleRejected("quality approval does not cover the same files as the color approval")
    if not _MODEL_REVISION.fullmatch(str(quality.get("model_revision", ""))):
        raise BundleRejected("quality approval has no 40-character FashionCLIP model revision")
    return {
        "approved_bundle_sha256": reader.sha256.hexdigest(),
        "approved_bundle_bytes": reader.size,
        "product_count": approval.get("product_count"),
        "model_revision": quality["model_revision"],
    }


def _approved_object(event: dict[str, Any]) -> tuple[str, str]:
    detail = event.get("detail") if isinstance(event, dict) else None
    try:
        return detail["bucket"]["name"], unquote_plus(detail["object"]["key"])
    except (KeyError, TypeError) as error:
        raise ReviewError("expected an EventBridge S3 Object Created event") from error


def receive_approval(event: dict[str, Any], s3: Any, sfn: Any, expected_bucket: str = "") -> dict[str, Any]:
    """Resume or fail the waiting run for an uploaded approved bundle. Other objects are ignored."""
    bucket, key = _approved_object(event)
    match = APPROVED_BUNDLE_KEY.fullmatch(key)
    if not match or (expected_bucket and bucket != expected_bucket):
        return {"status": "ignored", "reason": "not an approved bundle of this pipeline"}
    run_id = match[1]
    base = f"{REVIEW_PREFIX}/{run_id}"
    try:
        request = _read_json(s3, bucket, f"{base}/request.json")
    except Exception as error:
        if _error_code(error) in {"NoSuchKey", "404"} or type(error).__name__ == "NoSuchKey":
            return {"status": "ignored", "reason": "no pending review for this run", "run_id": run_id}
        raise
    if request.get("run_id") != run_id or request.get("approved_bundle_key") != key:
        raise ReviewError("review request does not match the uploaded bundle")
    token = _read_json(s3, bucket, f"{base}/task-token.json")["task_token"]
    decided_at = datetime.now(timezone.utc).isoformat()
    try:
        summary = inspect_bundle(s3, bucket, key)
    except BundleRejected as rejection:
        decision = {"status": "rejected", "run_id": run_id, "reason": str(rejection), "decided_at": decided_at}
        _send(sfn.send_task_failure, taskToken=token, error="ApprovalRejected", cause=str(rejection)[:32000])
    else:
        decision = {"status": "approved", "run_id": run_id, "approved_bundle_key": key, "decided_at": decided_at, **summary}
        _send(sfn.send_task_success, taskToken=token, output=json.dumps(decision, ensure_ascii=False))
    try:
        _put_json(s3, bucket, f"{base}/decision.json", decision, create_only=True)
    except Exception as error:
        if _error_code(error) not in {"PreconditionFailed", "412", "ConditionalRequestConflict", "409"}:
            raise
    return decision


def _send(call: Any, **kwargs: Any) -> None:
    """A run that already resumed, failed or timed out rejects its token; that is not an error here."""
    try:
        call(**kwargs)
    except Exception as error:
        if _error_code(error) not in {"TaskTimedOut", "TaskDoesNotExist", "InvalidToken"}:
            raise
