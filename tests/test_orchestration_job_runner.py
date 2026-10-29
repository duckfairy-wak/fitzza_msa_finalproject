from types import SimpleNamespace

import pytest

from infra.aws.orchestration.job_runner import JobExecutionError, JobNotStartedError, run_job


def contract():
    return {
        "schema_version": 1,
        "run_mode": "incremental",
        "run_id": "collection-20261027-01",
        "input_manifest_sha256": "0" * 64,
        "s3": {"bucket": "fitzza-data", "prefix": "pipeline/runs/collection-20261027-01"},
    }


class Missing(Exception):
    status = 404


class FakeApi:
    def __init__(self, statuses):
        self.statuses = iter(statuses)
        self.created = []

    def read_namespaced_job(self, **kwargs):
        value = next(self.statuses)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(status=SimpleNamespace(**value))

    def create_namespaced_job(self, **kwargs):
        self.created.append(kwargs)


def test_runner_creates_then_reuses_job_until_success():
    api = FakeApi([Missing(), {"active": 1}, {"succeeded": 1}])

    result = run_job(api, "crawler", contract(), "fitzza/crawler:reviewed", ["python", "-m", "crawler"], poll_seconds=0, sleep=lambda _: None)

    assert result["job_status"] == "SUCCEEDED"
    assert len(api.created) == 1


def test_runner_surfaces_failed_job():
    api = FakeApi([Missing(), {"failed": 1}])

    with pytest.raises(JobExecutionError, match="failed"):
        run_job(api, "fashion-clip", contract(), "fitzza/fashion-clip:reviewed", ["python", "-m", "index"], poll_seconds=0, sleep=lambda _: None)


class DictApi(FakeApi):
    """The EKS client returns Kubernetes JSON objects as plain dictionaries."""

    def read_namespaced_job(self, **kwargs):
        value = next(self.statuses)
        if isinstance(value, Exception):
            raise value
        return {"metadata": {"name": kwargs["name"]}, "status": value}


def test_runner_reads_status_from_kubernetes_json():
    api = DictApi([{"succeeded": 1}])

    result = run_job(api, "crawler", contract(), "fitzza/crawler:reviewed", ["python", "-m", "crawler"], poll_seconds=0, sleep=lambda _: None)

    assert result["job_status"] == "SUCCEEDED"
    assert api.created == []


def test_runner_returns_running_when_wait_budget_ends():
    api = DictApi([Missing(), {"active": 1}])

    result = run_job(api, "crawler", contract(), "fitzza/crawler:reviewed", ["python", "-m", "crawler"], wait_seconds=0, sleep=lambda _: None)

    assert result["job_status"] == "RUNNING"
    assert result["job_name"] == "fitzza-crawler-collection-20261027-01"
    assert len(api.created) == 1


def test_runner_does_not_create_job_outside_allowed_time():
    api = DictApi([Missing()])

    with pytest.raises(JobNotStartedError):
        run_job(api, "crawler", contract(), "fitzza/crawler:reviewed", ["python", "-m", "crawler"], can_create=lambda: False)

    assert api.created == []


def test_runner_keeps_observing_existing_job_outside_allowed_time():
    api = DictApi([{"active": 1}, {"succeeded": 1}])

    result = run_job(
        api, "crawler", contract(), "fitzza/crawler:reviewed", ["python", "-m", "crawler"],
        poll_seconds=0, sleep=lambda _: None, can_create=lambda: False,
    )

    assert result["job_status"] == "SUCCEEDED"
