"""Load validated crawler reviews into the local Docker Compose PostgreSQL.

Local QA only: every database call goes through the Compose ``postgres`` service,
so this script cannot reach RDS. Production imports follow
``infra/data-pipeline/README.md``. The rendered SQL is streamed to psql over stdin
and never written to disk.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any, Callable, Optional
from urllib.request import urlopen

try:
    from scripts.render_crawled_review_import import ImportRow, load_rows, render_sql
except ModuleNotFoundError:  # executed as `python scripts/load_local_reviews.py`
    from render_crawled_review_import import ImportRow, load_rows, render_sql


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / ".data" / "review-crawl-500-20261022" / "data"
DEFAULT_API_BASE_URL = "http://localhost:8080/api/v1"
POLL_SECONDS = 5
# No embedded double quotes, so Windows argument quoting cannot alter the command;
# the variables are the postgres container's own space-free Compose values.
PSQL_SHELL = "PGCLIENTENCODING=UTF8 psql -X -v ON_ERROR_STOP=1 -U $POSTGRES_USER -d $POSTGRES_DB"

SCHEMA_READY_SQL = (
    "SELECT count(*) FROM information_schema.columns "
    "WHERE table_schema = 'review_service' AND table_name = 'reviews' "
    "AND column_name = 'source_review_id';\n"
)
IMPORTED_COUNT_SQL = "SELECT count(*) FROM review_service.reviews WHERE source = 'MUSINSA';\n"
# Recreate the schema with its previous owner so a service account
# (review_service_app) can still run Flyway in it afterwards.
RESET_SCHEMA_SQL = """\
DO $$
DECLARE
    previous_owner text;
BEGIN
    SELECT pg_get_userbyid(nspowner) INTO previous_owner
    FROM pg_namespace WHERE nspname = 'review_service';
    EXECUTE 'DROP SCHEMA IF EXISTS review_service CASCADE';
    EXECUTE format('CREATE SCHEMA review_service AUTHORIZATION %I', coalesce(previous_owner, current_user));
END $$;
COMMENT ON SCHEMA review_service IS 'Owned by review-service';
"""
RESET_HINT = (
    "Check `docker compose logs --tail 60 review-service`. If it shows "
    "'Schema-validation: missing column', the local schema was created before Flyway; "
    "rerun with --reset-review-schema."
)

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


def review_service_status(runner: Runner) -> tuple[str, str]:
    """Return the review-service container (state, health), or ("", "") if absent."""
    result = runner(["docker", "compose", "ps", "--all", "--format", "json", "review-service"], None)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise LocalImportError(f"docker compose ps failed: {detail}")
    output = result.stdout.strip()
    if not output:
        return "", ""
    # Compose 2.21+ prints one JSON object per line; older releases print one array.
    entries = json.loads(output) if output.startswith("[") else [json.loads(line) for line in output.splitlines()]
    if not entries:
        return "", ""
    return str(entries[0].get("State", "")).lower(), str(entries[0].get("Health", "")).lower()


def review_schema_ready(runner: Runner) -> bool:
    return run_psql(runner, SCHEMA_READY_SQL, tuples_only=True).strip() == "1"


def wait_for_review_service(
    runner: Runner,
    timeout_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Wait until review-service is healthy and Flyway has created the V2 review table.

    A table alone is not enough: an old local schema can carry the V2 columns while
    review-service still fails Hibernate validation and never serves the reviews.
    """
    deadline = clock() + timeout_seconds
    while True:
        state, health = review_service_status(runner)
        if not state:
            raise LocalImportError("review-service container not found; run `docker compose up -d --build` first.")
        if state in ("exited", "dead"):
            raise LocalImportError(f"review-service is {state}. {RESET_HINT}")
        if state == "running" and health in ("healthy", "") and review_schema_ready(runner):
            return
        if clock() >= deadline:
            raise LocalImportError(
                f"review-service was not ready within {timeout_seconds:g}s "
                f"(state={state}, health={health or 'none'}). {RESET_HINT}"
            )
        sleep(POLL_SECONDS)


def reset_review_schema(runner: Runner) -> None:
    run_psql(runner, RESET_SCHEMA_SQL)
    result = runner(["docker", "compose", "restart", "review-service"], None)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise LocalImportError(f"failed to restart review-service: {detail}")


def busiest_product(rows: list[ImportRow]) -> tuple[int, int]:
    product_id, review_count = Counter(row.product_id for row in rows).most_common(1)[0]
    return product_id, review_count


def fetch_review_total(api_base_url: str, product_id: int, opener: Callable[..., Any]) -> int:
    url = f"{api_base_url.rstrip('/')}/reviews?productId={product_id}&size=1"
    with opener(url, timeout=10) as response:
        return int(json.load(response)["totalElements"])


def check_gateway(
    api_base_url: str,
    product_id: int,
    timeout_seconds: float,
    opener: Callable[..., Any] = urlopen,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int | None:
    """Return the public review total, or None if the Gateway never answered.

    The Gateway answers 503 until it refreshes its registry after review-service
    registers, which can take about a minute after a restart.
    """
    deadline = clock() + timeout_seconds
    while True:
        try:
            return fetch_review_total(api_base_url, product_id, opener)
        except (OSError, ValueError, KeyError):  # HTTPError and URLError are OSErrors
            if clock() >= deadline:
                return None
            sleep(POLL_SECONDS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load crawled Musinsa reviews into the local Docker Compose database for QA."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help="crawler data directory with one JSON file per product (default: %(default)s)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="crawler report.json (default: report.json next to the input directory)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail on any invalid review instead of skipping it",
    )
    parser.add_argument(
        "--reset-review-schema",
        action="store_true",
        help="drop and recreate the local review_service schema, then restart review-service "
        "(deletes local reviews and size surveys)",
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=180,
        help="how long to wait for review-service to create the review table (default: %(default)s)",
    )
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL, help="Gateway base URL to verify")
    parser.add_argument("--skip-api-check", action="store_true", help="do not call the Gateway afterwards")
    return parser


def main(
    argv: list[str] | None = None,
    runner: Runner = run_command,
    opener: Callable[..., Any] = urlopen,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    args = build_parser().parse_args(argv)
    input_directory = args.input
    report_path = args.report or input_directory.parent / "report.json"
    try:
        if not input_directory.is_dir():
            raise LocalImportError(f"crawler data directory not found: {input_directory} (pass --input)")
        if not report_path.is_file():
            raise LocalImportError(f"crawler report not found: {report_path} (pass --report)")
        rows, skipped = load_rows(input_directory, report_path, skip_invalid=not args.strict)
        sql = render_sql(rows)

        if args.reset_review_schema:
            print("Resetting the local review_service schema and restarting review-service.", file=sys.stderr)
            reset_review_schema(runner)
        wait_for_review_service(runner, args.wait_seconds, sleep, clock)
        print(run_psql(runner, sql).strip(), file=sys.stderr)
        imported = int(run_psql(runner, IMPORTED_COUNT_SQL, tuples_only=True).strip())
    except (LocalImportError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    summary: dict[str, Any] = {
        "rendered": len(rows),
        "skipped": len(skipped),
        "musinsa_reviews_in_db": imported,
    }
    if not args.skip_api_check:
        product_id, expected = busiest_product(rows)
        total = check_gateway(args.api_base_url, product_id, args.wait_seconds, opener, sleep, clock)
        summary["api_check"] = {"product_id": product_id, "expected_at_least": expected, "total_elements": total}
        if total is None or total < expected:
            print(
                f"warning: Gateway did not return the imported reviews for product {product_id}; "
                "the database import itself succeeded. The Gateway can take about a minute to "
                "pick up a restarted review-service; retry the API shortly.",
                file=sys.stderr,
            )
    print(json.dumps(summary, ensure_ascii=False))
    for message in skipped:
        print(f"skipped {message}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
