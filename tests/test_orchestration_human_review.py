import hashlib
import io
import json
import re
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from infra.aws.orchestration.human_review import (
    REVIEW_TIMEOUT_SECONDS,
    ReviewError,
    receive_approval,
    request_review,
)

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "collection-20261029-010000"
BUCKET = "fitzza-data"
APPROVED_KEY = f"pipeline/runs/{RUN_ID}/approved/bundle.tar.gz"
TOKEN = "secret-task-token"
FILES = {"config/color_map.json": "a" * 64, "data/top/1.json": "b" * 64}


class ClientError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class Body(io.BytesIO):
    pass


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.reads = []

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, **kwargs):
        if IfNoneMatch == "*" and (Bucket, Key) in self.objects:
            raise ClientError("PreconditionFailed")
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        self.reads.append(Key)
        if (Bucket, Key) not in self.objects:
            raise ClientError("NoSuchKey")
        return {"Body": Body(self.objects[(Bucket, Key)])}

    def json(self, key):
        return json.loads(self.objects[(BUCKET, key)])


class FakeSns:
    def __init__(self):
        self.published = []

    def publish(self, **kwargs):
        self.published.append(kwargs)


class FakeSfn:
    def __init__(self, error=None):
        self.success, self.failure, self.error = [], [], error

    def send_task_success(self, **kwargs):
        if self.error:
            raise ClientError(self.error)
        self.success.append(kwargs)

    def send_task_failure(self, **kwargs):
        if self.error:
            raise ClientError(self.error)
        self.failure.append(kwargs)


def contract():
    return {
        "schema_version": 1,
        "run_mode": "incremental",
        "run_id": RUN_ID,
        "input_manifest_sha256": "0" * 64,
        "s3": {"bucket": BUCKET, "prefix": f"pipeline/runs/{RUN_ID}"},
        "review_required_count": 12,
    }


def bundle(approval=None, quality=None, extra=None):
    members = {"data/top/1.json": {"product_id": 1}}
    if approval is not None:
        members["config/_APPROVED.json"] = approval
    if quality is not None:
        members["config/_QUALITY_APPROVED.json"] = quality
    members.update(extra or {})
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as archive:
        for name, value in members.items():
            data = json.dumps(value).encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return raw.getvalue()


def approved_bundle(**changes):
    approval = {"human_color_review_approved": True, "product_count": 3000, "files": FILES}
    quality = {"approved": True, "files": FILES, "model_revision": "7e3ba62ce16b379a1ab479346b66f192e76f51b7"}
    quality.update(changes)
    return bundle(approval, quality)


def raw_marker_bundle(marker):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w:gz") as archive:
        info = tarfile.TarInfo("config/_APPROVED.json")
        info.size = len(marker)
        archive.addfile(info, io.BytesIO(marker))
    return raw.getvalue()


def uploaded(s3, data, bucket=BUCKET, key=APPROVED_KEY):
    s3.objects[(bucket, key)] = data
    return {"source": "aws.s3", "detail-type": "Object Created", "detail": {"bucket": {"name": bucket}, "object": {"key": key}}}


def requested(s3):
    request_review({"contract": contract(), "task_token": TOKEN}, s3, now=datetime(2026, 10, 29, 1, 0, tzinfo=timezone.utc))


def test_request_keeps_token_outside_pipeline_prefix_and_records_request():
    s3 = FakeS3()

    request = request_review(
        {"contract": contract(), "task_token": TOKEN}, s3, now=datetime(2026, 10, 29, 1, 0, tzinfo=timezone.utc)
    )

    token_key = f"orchestration/review/{RUN_ID}/task-token.json"
    assert s3.json(token_key)["task_token"] == TOKEN
    assert all(not key.startswith("pipeline/") or TOKEN.encode() not in body for (_, key), body in s3.objects.items())
    assert s3.json(f"orchestration/review/{RUN_ID}/request.json") == request
    assert request["approved_bundle_key"] == APPROVED_KEY
    assert request["deadline"] == "2026-11-01T01:00:00+00:00"
    assert request["notified"] is False


def test_notification_is_sent_only_when_a_topic_is_configured():
    s3, sns = FakeS3(), FakeSns()

    request_review({"contract": contract(), "task_token": TOKEN}, s3, sns, "")
    assert sns.published == []

    request_review({"contract": contract(), "task_token": TOKEN}, s3, sns, "arn:aws:sns:ap-northeast-2:111111111111:review")
    message = sns.published[0]
    assert message["Subject"].isascii() and len(message["Subject"]) < 100 and RUN_ID in message["Subject"]
    assert f"s3://{BUCKET}/pipeline/runs/{RUN_ID}/jev/review-bundle.tar.gz" in message["Message"]
    assert f"s3://{BUCKET}/{APPROVED_KEY}" in message["Message"]
    assert "--require-quality" in message["Message"]
    assert "검수 대상: 12건" in message["Message"]
    assert TOKEN not in message["Message"]


@pytest.mark.parametrize(
    "event",
    [{}, {"contract": contract()}, {"contract": {**contract(), "run_id": "Bad_ID"}, "task_token": TOKEN}],
)
def test_malformed_review_request_is_rejected(event):
    with pytest.raises(ReviewError):
        request_review(event, FakeS3())


def test_valid_approved_bundle_resumes_the_run_once():
    s3, sfn = FakeS3(), FakeSfn()
    requested(s3)
    data = approved_bundle()

    decision = receive_approval(uploaded(s3, data), s3, sfn, BUCKET)

    assert decision["status"] == "approved"
    assert sfn.failure == [] and sfn.success[0]["taskToken"] == TOKEN
    output = json.loads(sfn.success[0]["output"])
    assert output["approved_bundle_sha256"] == hashlib.sha256(data).hexdigest()
    assert output["approved_bundle_bytes"] == len(data)
    assert output["model_revision"] == "7e3ba62ce16b379a1ab479346b66f192e76f51b7"
    assert s3.json(f"orchestration/review/{RUN_ID}/decision.json")["status"] == "approved"

    again = receive_approval(uploaded(s3, data), s3, FakeSfn(error="TaskTimedOut"), BUCKET)
    assert again["status"] == "approved"


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (bundle({"human_color_review_approved": True, "files": FILES}, None), "quality approval"),
        (bundle(None, {"approved": True, "files": FILES}), "color approval"),
        (approved_bundle(approved=False), "quality approval"),
        (approved_bundle(files={"other": "c" * 64}), "same files"),
        (approved_bundle(model_revision="main"), "model revision"),
        (b"not a tarball", "readable tar.gz"),
        (raw_marker_bundle(b"\xff\xfe not utf-8"), "readable tar.gz"),
        (raw_marker_bundle(b"[" * 100000 + b"]" * 100000), "readable tar.gz"),
    ],
)
def test_invalid_bundle_fails_the_run_with_a_reason(data, reason):
    s3, sfn = FakeS3(), FakeSfn()
    requested(s3)

    decision = receive_approval(uploaded(s3, data), s3, sfn, BUCKET)

    assert decision["status"] == "rejected" and reason in decision["reason"]
    assert sfn.success == []
    assert sfn.failure[0]["error"] == "ApprovalRejected" and sfn.failure[0]["taskToken"] == TOKEN


@pytest.mark.parametrize(
    ("bucket", "key"),
    [
        (BUCKET, f"pipeline/runs/{RUN_ID}/jev/review-bundle.tar.gz"),
        (BUCKET, f"pipeline/runs/{RUN_ID}/approved/other.tar.gz"),
        ("another-bucket", APPROVED_KEY),
    ],
)
def test_unrelated_objects_are_ignored_without_reading_tokens(bucket, key):
    s3, sfn = FakeS3(), FakeSfn()
    requested(s3)
    s3.reads.clear()

    result = receive_approval(uploaded(s3, approved_bundle(), bucket, key), s3, sfn, BUCKET)

    assert result["status"] == "ignored"
    assert s3.reads == [] and sfn.success == [] and sfn.failure == []


def test_bundle_without_a_pending_request_is_ignored():
    s3, sfn = FakeS3(), FakeSfn()

    result = receive_approval(uploaded(s3, approved_bundle()), s3, sfn, BUCKET)

    assert result["status"] == "ignored" and sfn.success == []


def test_request_that_does_not_match_the_upload_is_an_error():
    s3, sfn = FakeS3(), FakeSfn()
    requested(s3)
    request_key = (BUCKET, f"orchestration/review/{RUN_ID}/request.json")
    request = json.loads(s3.objects[request_key])
    s3.objects[request_key] = json.dumps({**request, "approved_bundle_key": "pipeline/runs/x/approved/bundle.tar.gz"}).encode()

    with pytest.raises(ReviewError):
        receive_approval(uploaded(s3, approved_bundle()), s3, sfn, BUCKET)


def test_unexpected_step_functions_errors_are_raised():
    s3 = FakeS3()
    requested(s3)

    with pytest.raises(ClientError):
        receive_approval(uploaded(s3, approved_bundle()), s3, FakeSfn(error="AccessDeniedException"), BUCKET)


def test_review_timeout_matches_the_state_machine():
    asl = json.loads((ROOT / "infra/data-pipeline/orchestration.asl.json").read_text(encoding="utf-8"))
    assert asl["States"]["WaitForHumanReview"]["TimeoutSeconds"] == REVIEW_TIMEOUT_SECONDS


def test_template_creates_no_review_resources_by_default():
    template = (ROOT / "infra/aws/cloudformation/orchestration.yaml").read_text(encoding="utf-8")
    for parameter in ("EnableReviewNotification", "EnableApprovalEvents"):
        block = template[template.index(f"  {parameter}:"):]
        assert re.search(r"Default: 'false'", block.split("\n\n")[0])
    for resource, condition in (
        ("ReviewNotificationTopic", "ReviewNotificationEnabled"),
        ("ReviewNotificationSubscription", "HasReviewNotificationEmail"),
        ("ApprovalUploadedRule", "ApprovalEventsEnabled"),
        ("ApprovalReceiverInvokePermission", "ApprovalEventsEnabled"),
    ):
        block = template[template.index(f"  {resource}:\n"):]
        assert f"    Condition: {condition}\n" in block.split("\n\n")[0]
