"""Lambda entrypoint for a Crawler/FashionCLIP Job runner."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from .eks_kubernetes_api import EksKubernetesApi
from .job_runner import run_job
from .job_spec import DEFAULT_NODE_SELECTOR
from .operating_window import DEFAULT_RUN_WINDOW, is_within_window, parse_window


def lambda_handler(event, _context):
    stage = os.environ["PIPELINE_STAGE"]
    image = os.environ["PIPELINE_IMAGE"]
    command = json.loads(os.environ["PIPELINE_COMMAND_JSON"])
    node_selector = json.loads(os.environ.get("PIPELINE_NODE_SELECTOR_JSON") or json.dumps(DEFAULT_NODE_SELECTOR))
    window = os.environ.get("PIPELINE_RUN_WINDOW") or DEFAULT_RUN_WINDOW
    parse_window(window)
    api = EksKubernetesApi(os.environ["EKS_CLUSTER_NAME"], os.environ.get("AWS_REGION", "ap-northeast-2"))
    return run_job(
        api,
        stage,
        event,
        image,
        command,
        namespace=os.environ.get("EKS_NAMESPACE", "fitzza"),
        wait_seconds=float(os.environ.get("PIPELINE_JOB_WAIT_SECONDS", "600")),
        node_selector=node_selector,
        can_create=lambda: is_within_window(datetime.now(timezone.utc), window),
    )
