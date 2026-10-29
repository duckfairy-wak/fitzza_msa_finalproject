import json

from infra.aws.orchestration import runner_lambda


def test_runner_lambda_passes_configuration(monkeypatch):
    calls = {}

    class FakeApi:
        def __init__(self, cluster, region):
            calls["cluster"] = (cluster, region)

    def fake_run_job(api, stage, event, image, command, **kwargs):
        calls.update(stage=stage, image=image, command=command, **kwargs)
        return {"job_status": "RUNNING"}

    monkeypatch.setattr(runner_lambda, "EksKubernetesApi", FakeApi)
    monkeypatch.setattr(runner_lambda, "run_job", fake_run_job)
    monkeypatch.setenv("PIPELINE_STAGE", "crawler")
    monkeypatch.setenv("PIPELINE_IMAGE", "fitzza/crawler:reviewed")
    monkeypatch.setenv("PIPELINE_COMMAND_JSON", json.dumps(["python", "-m", "src.cli"]))
    monkeypatch.setenv("EKS_CLUSTER_NAME", "fitzza-prod")
    monkeypatch.setenv("PIPELINE_JOB_WAIT_SECONDS", "540")
    monkeypatch.delenv("PIPELINE_NODE_SELECTOR_JSON", raising=False)
    monkeypatch.delenv("PIPELINE_RUN_WINDOW", raising=False)

    result = runner_lambda.lambda_handler({"run_id": "collection-20261029-01"}, None)

    assert result == {"job_status": "RUNNING"}
    assert calls["cluster"] == ("fitzza-prod", "ap-northeast-2")
    assert calls["wait_seconds"] == 540
    assert calls["node_selector"] == {"kubernetes.io/arch": "arm64"}
    assert callable(calls["can_create"])


def test_invalid_run_window_fails_before_contacting_eks(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("EKS must not be contacted with an invalid window")

    monkeypatch.setattr(runner_lambda, "EksKubernetesApi", unexpected)
    monkeypatch.setenv("PIPELINE_STAGE", "crawler")
    monkeypatch.setenv("PIPELINE_IMAGE", "fitzza/crawler:reviewed")
    monkeypatch.setenv("PIPELINE_COMMAND_JSON", "[\"python\"]")
    monkeypatch.setenv("EKS_CLUSTER_NAME", "fitzza-prod")
    monkeypatch.setenv("PIPELINE_RUN_WINDOW", "weekdays")

    try:
        runner_lambda.lambda_handler({}, None)
    except ValueError as error:
        assert "run window" in str(error)
    else:
        raise AssertionError("invalid window was accepted")
