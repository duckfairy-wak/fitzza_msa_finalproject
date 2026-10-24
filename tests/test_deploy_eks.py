import subprocess
from unittest.mock import patch

import pytest

from scripts.deploy_eks import APPLICATIONS, deploy


def test_base_rollouts_finish_before_application_apply():
    assert "vton-worker" in APPLICATIONS
    with patch("scripts.deploy_eks.subprocess.run") as run:
        deploy("rendered.yaml")
    commands = [call.args[0] for call in run.call_args_list]
    apply_indexes = [i for i, command in enumerate(commands) if command[1] == "apply"]
    assert len(apply_indexes) == 3
    assert commands[0][-1] == "fitzza.io/workload!=application"
    assert commands[1][-1] == "app.kubernetes.io/name in (config-service,discovery-service)"
    for resource in ("deployment/config-service", "deployment/discovery-service",
                     "deployment/redis", "statefulset/qdrant"):
        assert any(resource in command for command in commands[2:apply_indexes[2]])
    for app in APPLICATIONS:
        assert any(f"deployment/{app}" in command for command in commands[apply_indexes[2] + 1:])
    assert all(call.kwargs["check"] for call in run.call_args_list)
    assert all(call.kwargs["timeout"] == 960 for call in run.call_args_list)
    assert all("--timeout=900s" in command for command in commands if "rollout" in command)


def test_config_server_failure_prevents_application_apply():
    with patch("scripts.deploy_eks.subprocess.run") as run:
        run.side_effect = [None, None, subprocess.CalledProcessError(1, "kubectl")]
        with pytest.raises(subprocess.CalledProcessError):
            deploy("rendered.yaml")
    assert len(run.call_args_list) == 3


@pytest.mark.parametrize("completed_calls", [0, 2])
def test_timeout_propagates_and_stops_deployment(completed_calls):
    timeout = subprocess.TimeoutExpired("kubectl", 960)
    with patch("scripts.deploy_eks.subprocess.run") as run:
        run.side_effect = [None] * completed_calls + [timeout]
        with pytest.raises(subprocess.TimeoutExpired) as error:
            deploy("rendered.yaml")
    assert error.value is timeout
    assert len(run.call_args_list) == completed_calls + 1
