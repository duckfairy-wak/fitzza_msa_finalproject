import json

import pytest

from infra.aws.orchestration import handler
from infra.aws.orchestration.handler import ContractError, StageNotEnabledError, initialize_run, write_status


def contract():
    return {
        "schema_version": 1,
        "run_mode": "full",
        "run_id": "collection-20261027-01",
        "input_manifest_sha256": "0" * 64,
        "s3": {
            "bucket": "fitzza-data",
            "prefix": "pipeline/runs/collection-20261027-01",
        },
    }


class Body:
    def __init__(self, value):
        self.value = value

    def read(self):
        return self.value


class FakeS3:
    class NoSuchKey(Exception):
        pass

    class Exceptions:
        pass

    exceptions = Exceptions()
    exceptions.NoSuchKey = NoSuchKey

    def __init__(self, approval=None, manifest=b"manifest", checkpoint=None):
        self.approval = approval
        self.manifest = manifest
        self.checkpoint = checkpoint
        self.put = None

    def put_object(self, **kwargs):
        self.put = kwargs

    def get_object(self, **kwargs):
        if kwargs["Key"] == "manifest.json":
            return {"Body": Body(self.manifest)}
        if kwargs["Key"] == "pipeline/state/incremental.json":
            if self.checkpoint is None:
                raise self.NoSuchKey()
            return {"Body": Body(json.dumps(self.checkpoint).encode())}
        return {"Body": Body(json.dumps(self.approval).encode())}


def test_write_status_persists_contract_status():
    s3 = FakeS3()
    event = {**contract(), "status": "SUCCEEDED"}

    result = write_status(event, s3)

    assert result["status"] == "SUCCEEDED"
    assert s3.put["Key"].endswith("/status/SUCCEEDED.json")
    assert json.loads(s3.put["Body"])["run_id"] == event["run_id"]


def test_contract_rejects_a_mismatched_prefix():
    event = {**contract(), "status": "RUNNING", "s3": {"bucket": "fitzza-data", "prefix": "pipeline/runs/other"}}

    with pytest.raises(ContractError):
        write_status(event, FakeS3())


def test_initialize_run_fingerprints_manifest_and_builds_paths():
    result = initialize_run(
        {"run_mode": "incremental", "bucket": "fitzza-data", "manifest_key": "manifest.json"},
        FakeS3(manifest=b'{"products":[{"product_id":"101"}]}'),
    )

    assert result["run_mode"] == "incremental"
    assert result["input_manifest_sha256"]
    assert result["baseline"]["product_count"] == 1
    assert result["checkpoint"]["last_successful_run_id"] is None
    assert result["s3"]["prefix"].startswith("pipeline/runs/collection-")
    assert result["stages"]["jev"]["success_marker"].endswith("/jev/_SUCCESS.json")


def test_initialize_run_rejects_a_full_run_without_manual_approval():
    with pytest.raises(ContractError, match="manual_approved"):
        initialize_run(
            {"run_mode": "full", "bucket": "fitzza-data", "baseline_manifest_key": "manifest.json"},
            FakeS3(manifest=b'{"products":[{"product_id":"101"}]}'),
        )


@pytest.mark.parametrize("stage", ["validate_import", "jev"])
def test_unimplemented_stages_fail_closed(monkeypatch, stage):
    monkeypatch.setenv("ORCHESTRATION_ACTION", "not_enabled")
    monkeypatch.setenv("PIPELINE_STAGE_NAME", stage)
    monkeypatch.setattr(handler, "_s3", lambda: pytest.fail("a placeholder adapter must not touch S3"))

    with pytest.raises(StageNotEnabledError, match="collection-20261027-01"):
        handler.lambda_handler(contract(), None)


def test_placeholder_requires_a_known_stage(monkeypatch):
    monkeypatch.setenv("ORCHESTRATION_ACTION", "not_enabled")
    monkeypatch.setenv("PIPELINE_STAGE_NAME", "crawler")

    with pytest.raises(ContractError):
        handler.lambda_handler(contract(), None)


def test_review_actions_are_routed(monkeypatch):
    calls = []
    monkeypatch.setattr(handler, "_s3", lambda: "s3")
    monkeypatch.setattr(handler.boto3, "client", lambda name, **kwargs: f"{name}-client")
    monkeypatch.setattr(handler, "request_review", lambda event, s3, sns, topic: calls.append(("request", s3, sns, topic)) or {})
    monkeypatch.setattr(handler, "receive_approval", lambda event, s3, sfn, bucket: calls.append(("receive", s3, sfn, bucket)) or {})
    monkeypatch.setenv("PIPELINE_BUCKET", "fitzza-data")

    monkeypatch.setenv("ORCHESTRATION_ACTION", "review_requester")
    monkeypatch.delenv("REVIEW_TOPIC_ARN", raising=False)
    handler.lambda_handler({}, None)
    monkeypatch.setenv("REVIEW_TOPIC_ARN", "arn:aws:sns:ap-northeast-2:111111111111:review")
    handler.lambda_handler({}, None)
    monkeypatch.setenv("ORCHESTRATION_ACTION", "approval_receiver")
    handler.lambda_handler({}, None)

    assert calls == [
        ("request", "s3", None, ""),
        ("request", "s3", "sns-client", "arn:aws:sns:ap-northeast-2:111111111111:review"),
        ("receive", "s3", "stepfunctions-client", "fitzza-data"),
    ]


def test_removed_approval_checker_action_is_rejected(monkeypatch):
    monkeypatch.setenv("ORCHESTRATION_ACTION", "approval_checker")

    with pytest.raises(ContractError):
        handler.lambda_handler(contract(), None)
