from infra.aws.orchestration.job_spec import render_job


def contract():
    return {
        "schema_version": 1,
        "run_mode": "incremental",
        "run_id": "collection-20261027-01",
        "input_manifest_sha256": "0" * 64,
        "s3": {"bucket": "fitzza-data", "prefix": "pipeline/runs/collection-20261027-01"},
    }


def test_job_isolated_and_contract_bound():
    job = render_job("crawler", contract(), "fitzza/crawler:reviewed", ["python", "-m", "crawler"])
    spec = job["spec"]["template"]["spec"]
    env = {item["name"]: item["value"] for item in spec["containers"][0]["env"]}

    assert job["metadata"]["name"] == "fitzza-crawler-collection-20261027-01"
    assert spec["nodeSelector"] == {"kubernetes.io/arch": "arm64"}
    assert spec["containers"][0]["resources"]["limits"]["cpu"] == "2"
    assert env["PIPELINE_S3_PREFIX"].endswith(contract()["run_id"])


def test_only_supported_pipeline_stages_are_rendered():
    try:
        render_job("reviews", contract(), "fitzza/reviews:reviewed", ["python", "-m", "reviews"])
    except ValueError as error:
        assert "crawler, fashion-clip, or integrity" in str(error)
    else:
        raise AssertionError("unsupported stage was accepted")


def test_integrity_job_can_access_qdrant_and_baseline_manifest():
    integrity_contract = {
        **contract(),
        "run_mode": "integrity",
        "baseline": {"manifest_key": "pipeline/current/manifest.json"},
    }

    job = render_job("integrity", integrity_contract, "fitzza/pipeline-integrity:reviewed", ["python", "/app/integrity_check.py"])
    spec = job["spec"]["template"]["spec"]
    env = {item["name"]: item["value"] for item in spec["containers"][0]["env"]}

    assert spec["serviceAccountName"] == "fitzza-pipeline"
    assert spec["containers"][0]["name"] == "integrity"
    assert job["metadata"]["labels"]["fitzza.io/qdrant-client"] == "true"
    assert env["PIPELINE_BASELINE_MANIFEST_KEY"] == "pipeline/current/manifest.json"


def test_dedicated_pipeline_node_can_be_selected():
    selector = {"kubernetes.io/arch": "arm64", "fitzza.io/pipeline-worker": "true"}

    job = render_job("crawler", contract(), "fitzza/crawler:reviewed", ["python", "-m", "crawler"], node_selector=selector)

    assert job["spec"]["template"]["spec"]["nodeSelector"] == selector


def test_empty_node_selector_is_rejected():
    try:
        render_job("crawler", contract(), "fitzza/crawler:reviewed", ["python", "-m", "crawler"], node_selector={})
    except ValueError as error:
        assert "node_selector" in str(error)
    else:
        raise AssertionError("empty node selector was accepted")
