"""Build the deployment ZIP for the data-pipeline Lambda adapters."""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "infra/aws/orchestration/handler.py",
    "infra/aws/orchestration/human_review.py",
    "infra/aws/orchestration/runner_lambda.py",
    "infra/aws/orchestration/job_runner.py",
    "infra/aws/orchestration/job_spec.py",
    "infra/aws/orchestration/eks_kubernetes_api.py",
    "infra/aws/orchestration/operating_window.py",
)


def package(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for package_name in ("infra", "infra/aws", "infra/aws/orchestration"):
            archive.writestr(f"{package_name}/__init__.py", "")
        for source in SOURCES:
            path = ROOT / source
            archive.write(path, source)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    package(args.output)


if __name__ == "__main__":
    main()
