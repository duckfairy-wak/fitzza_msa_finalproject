import zipfile

from scripts.package_orchestration_lambda import package


def test_package_contains_all_adapter_modules(tmp_path):
    output = tmp_path / "orchestration.zip"

    package(output)

    with zipfile.ZipFile(output) as archive:
        assert "infra/aws/orchestration/handler.py" in archive.namelist()
        assert "infra/aws/orchestration/runner_lambda.py" in archive.namelist()
        assert "infra/aws/orchestration/operating_window.py" in archive.namelist()
        assert "infra/aws/orchestration/human_review.py" in archive.namelist()
