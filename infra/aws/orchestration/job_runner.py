"""Idempotent Kubernetes Job runner used by the pipeline adapter."""

from __future__ import annotations

import time
from typing import Any, Callable

from .job_spec import render_job


class JobExecutionError(RuntimeError):
    """Raised when a Kubernetes Job fails or exceeds its deadline."""


class JobNotStartedError(JobExecutionError):
    """Raised when a new Job may not be created now, for example outside the run window."""


def _status(job: Any) -> str:
    value = getattr(job, "status", None) or {}
    if isinstance(job, dict):
        value = job.get("status") or {}
    if isinstance(value, dict):
        succeeded, failed, active = value.get("succeeded"), value.get("failed"), value.get("active")
    else:
        succeeded, failed, active = getattr(value, "succeeded", None), getattr(value, "failed", None), getattr(value, "active", None)
    if succeeded:
        return "SUCCEEDED"
    if failed:
        return "FAILED"
    if active:
        return "RUNNING"
    return "PENDING"


def run_job(
    api: Any,
    stage: str,
    contract: dict[str, Any],
    image: str,
    command: list[str],
    namespace: str = "fitzza",
    wait_seconds: float = 600,
    poll_seconds: float = 15,
    sleep: Callable[[float], None] = time.sleep,
    node_selector: dict[str, str] | None = None,
    can_create: Callable[[], bool] = lambda: True,
) -> dict[str, Any]:
    """Create or observe one deterministic Job for at most wait_seconds.

    A Lambda invocation cannot outlive a pipeline Job, so an unfinished Job is reported as
    RUNNING or PENDING and the state machine calls again. The Job's own activeDeadlineSeconds
    bounds the total run time.
    """
    body = render_job(stage, contract, image, command, node_selector=node_selector)
    name = body["metadata"]["name"]
    try:
        existing = api.read_namespaced_job(name=name, namespace=namespace)
    except Exception as error:
        if getattr(error, "status", None) != 404:
            raise JobExecutionError(f"could not inspect {name}") from error
        if not can_create():
            raise JobNotStartedError(f"{name} was not created: new pipeline Jobs are not allowed now") from None
        api.create_namespaced_job(namespace=namespace, body=body)
        existing = api.read_namespaced_job(name=name, namespace=namespace)

    deadline = time.monotonic() + wait_seconds
    while True:
        state = _status(existing)
        if state == "FAILED":
            raise JobExecutionError(f"pipeline Job failed: {name}")
        if state == "SUCCEEDED" or time.monotonic() >= deadline:
            return {**contract, "stage": stage, "job_name": name, "job_status": state}
        sleep(poll_seconds)
        existing = api.read_namespaced_job(name=name, namespace=namespace)
