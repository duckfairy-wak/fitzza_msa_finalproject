"""Load curated products into the local Docker Compose PostgreSQL.

Local QA only: Compose ``postgres`` only — cannot reach RDS. Production imports
use ``scripts/render_crawled_product_import.py`` then psql from a short-lived
private-network pod (same pattern as reviews).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable, Optional

try:
    from scripts.render_crawled_product_import import load_bundle, render_sql
except ModuleNotFoundError:
    from render_crawled_product_import import load_bundle, render_sql


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / ".data" / "collection-20261025-01"
PSQL_SHELL = "PGCLIENTENCODING=UTF8 psql -X -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB"
PRODUCT_COUNT_SQL = "SELECT count(*) FROM product_service.product WHERE source = 'musinsa';\n"
SCHEMA_READY_SQL = (
    "SELECT count(*) FROM information_schema.tables "
    "WHERE table_schema = 'product_service' AND table_name = 'product';\n"
)
POLL_SECONDS = 5

Runner = Callable[[list[str], Optional[str]], subprocess.CompletedProcess]


class LocalImportError(RuntimeError):
    """Raised when the local import cannot continue."""


def run_command(command: list[str], stdin_text: str | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            input=stdin_text,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
    except FileNotFoundError as error:
        raise LocalImportError("docker command not found; install Docker Desktop and retry") from error


def run_psql(runner: Runner, sql: str, *, tuples_only: bool = False) -> str:
    shell = f"{PSQL_SHELL} -tA" if tuples_only else PSQL_SHELL
    result = runner(["docker", "compose", "exec", "-T", "postgres", "sh", "-c", shell], sql)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise LocalImportError(f"psql in the Compose postgres service failed: {detail}")
    return result.stdout


def product_schema_ready(runner: Runner) -> bool:
    return run_psql(runner, SCHEMA_READY_SQL, tuples_only=True).strip() == "1"


def wait_for_product_schema(
    runner: Runner,
    timeout_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    deadline = clock() + timeout_seconds
    while True:
        try:
            if product_schema_ready(runner):
                return
        except LocalImportError:
            pass
        if clock() >= deadline:
            raise LocalImportError(
                f"product_service.product was not ready within {timeout_seconds:g}s; "
                "run `docker compose up -d --build product-service` first."
            )
        sleep(POLL_SECONDS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load curated Musinsa products into the local Docker Compose database."
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        default=DEFAULT_RUN,
        help="downloaded run directory containing curated/ and status.json",
    )
    parser.add_argument("--data", type=Path, help="override curated/data directory")
    parser.add_argument("--status", type=Path, help="override status.json")
    parser.add_argument("--manifest", type=Path, help="override curated/manifest.json")
    parser.add_argument("--images", type=Path, help="override images/products directory")
    parser.add_argument(
        "--image-failures",
        type=Path,
        help="override audit/image-download-failures/products",
    )
    parser.add_argument("--image-public-base-url", help="HTTPS base for S3 object keys")
    parser.add_argument("--run-id", default="collection-20261025-01")
    parser.add_argument("--expected-count", type=int, default=3000)
    parser.add_argument("--skip-invalid", action="store_true")
    parser.add_argument(
        "--skip-status-check",
        action="store_true",
        help="fixture mode: do not require status.json / 3000 count",
    )
    parser.add_argument("--wait-seconds", type=float, default=180)
    return parser


def main(
    argv: list[str] | None = None,
    runner: Runner = run_command,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    args = build_parser().parse_args(argv)
    run_dir = args.run_dir
    data = args.data or (run_dir / "curated" / "data")
    status = args.status or (run_dir / "status.json")
    manifest = args.manifest or (run_dir / "curated" / "manifest.json")
    images = args.images or (run_dir / "images" / "products")
    failures = args.image_failures or (
        run_dir / "audit" / "image-download-failures" / "products"
    )

    try:
        if not data.is_dir():
            raise LocalImportError(f"curated data directory not found: {data}")
        status_path = None if args.skip_status_check else status
        if status_path is not None and not status_path.is_file():
            raise LocalImportError(f"status.json not found: {status_path}")
        manifest_path = manifest if manifest.is_file() else None
        images_path = images if images.is_dir() else None
        failures_path = failures if failures.is_dir() else None

        expected_count = None if args.skip_status_check else args.expected_count
        bundle = load_bundle(
            data_root=data,
            status_path=status_path,
            manifest_path=manifest_path,
            images_root=images_path,
            failures_root=failures_path,
            image_key_prefix=f"pipeline/runs/{args.run_id}/images/products",
            image_public_base_url=args.image_public_base_url,
            expected_count=expected_count,
            skip_invalid=args.skip_invalid,
        )
        if expected_count is not None and not args.skip_invalid and len(bundle.products) != expected_count:
            raise LocalImportError(f"loaded {len(bundle.products)} products, expected {expected_count}")
        sql = render_sql(bundle, run_id=args.run_id)

        wait_for_product_schema(runner, args.wait_seconds, sleep, clock)
        print(run_psql(runner, sql).strip(), file=sys.stderr)
        imported = int(run_psql(runner, PRODUCT_COUNT_SQL, tuples_only=True).strip())
    except (LocalImportError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "products": len(bundle.products),
                "images": len(bundle.images),
                "options": len(bundle.options),
                "skipped": len(bundle.skipped),
                "image_failure_files": bundle.image_failure_files,
                "musinsa_products_in_db": imported,
            },
            ensure_ascii=False,
        )
    )
    for message in bundle.skipped:
        print(f"skipped {message}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
