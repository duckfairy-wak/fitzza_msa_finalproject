import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.error import HTTPError

from scripts.load_local_reviews import (
    IMPORTED_COUNT_SQL,
    SCHEMA_READY_SQL,
    LocalImportError,
    main,
    reset_review_schema,
    wait_for_review_service,
)


def completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeCompose:
    """Answers psql calls the way the Compose postgres service would."""

    def __init__(self, ready_answers=("1",), imported="2", statuses=('{"State":"running","Health":"healthy"}',)):
        self.ready_answers = list(ready_answers)
        self.statuses = list(statuses)
        self.imported = imported
        self.calls = []

    def __call__(self, command, stdin_text):
        self.calls.append((command, stdin_text))
        if command[:3] == ["docker", "compose", "restart"]:
            return completed()
        if command[:3] == ["docker", "compose", "ps"]:
            status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
            return completed(f"{status}\n")
        if stdin_text == SCHEMA_READY_SQL:
            answer = self.ready_answers.pop(0) if len(self.ready_answers) > 1 else self.ready_answers[0]
            return completed(f"{answer}\n")
        if stdin_text == IMPORTED_COUNT_SQL:
            return completed(f"{self.imported}\n")
        return completed("BEGIN\nCREATE TABLE\nCOPY 2\nINSERT 0 2\nCOMMIT\n")

    def sql_sent(self):
        return [stdin for _, stdin in self.calls if stdin]


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class LoadLocalReviewsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        (self.root / "report.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "selected_product_count": 1,
                    "completed_product_count": 1,
                    "failed_product_count": 0,
                }
            ),
            encoding="utf-8",
        )
        self.clock = FakeClock()

    def write_reviews(self, reviews):
        (self.data / "123.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source": "musinsa",
                    "product_id": "123",
                    "collected_review_count": len(reviews),
                    "reviews": reviews,
                }
            ),
            encoding="utf-8",
        )

    @staticmethod
    def review(source_review_id, content="좋아요"):
        return {
            "source_review_id": source_review_id,
            "grade": "5",
            "content": content,
            "image_urls": [],
            "created_at": "2026-10-20T01:02:03Z",
        }

    def run_main(self, compose, *extra, opener=None):
        opener = opener or (lambda url, timeout: FakeResponse(b'{"totalElements": 2}'))
        return main(
            ["--input", str(self.data), *extra],
            runner=compose,
            opener=opener,
            sleep=self.clock.sleep,
            clock=self.clock,
        )

    def test_streams_rendered_sql_to_compose_postgres_without_writing_a_file(self):
        self.write_reviews([self.review(1), self.review(2)])
        compose = FakeCompose()

        self.assertEqual(self.run_main(compose), 0)

        import_command, import_sql = next(call for call in compose.calls if "COPY" in (call[1] or ""))
        self.assertEqual(import_command[:7], ["docker", "compose", "exec", "-T", "postgres", "sh", "-c"])
        self.assertIn("ON_ERROR_STOP=1", import_command[7])
        self.assertIn("INSERT INTO review_service.reviews", import_sql)
        self.assertIn("좋아요", import_sql)
        self.assertEqual(list(self.root.rglob("*.sql")), [])

    def test_waits_until_review_service_is_healthy_and_owns_the_v2_table(self):
        compose = FakeCompose(
            ready_answers=("0", "1"),
            statuses=(
                '{"State":"running","Health":"starting"}',
                '{"State":"running","Health":"healthy"}',
                '{"State":"running","Health":"healthy"}',
            ),
        )

        wait_for_review_service(compose, 60, self.clock.sleep, self.clock)

        self.assertEqual(len(self.clock.sleeps), 2)

    def test_accepts_the_json_array_format_of_older_compose_releases(self):
        compose = FakeCompose(statuses=('[{"State":"running","Health":"healthy"}]',))

        wait_for_review_service(compose, 60, self.clock.sleep, self.clock)

        self.assertEqual(self.clock.sleeps, [])

    def test_exited_review_service_stops_before_importing_and_points_to_reset(self):
        self.write_reviews([self.review(1)])
        compose = FakeCompose(statuses=('{"State":"exited","Health":""}',))

        with self.assertRaisesRegex(LocalImportError, "--reset-review-schema"):
            wait_for_review_service(compose, 60, self.clock.sleep, self.clock)
        self.assertEqual(self.run_main(compose), 1)
        self.assertFalse(any("COPY" in sql for sql in compose.sql_sent()))

    def test_missing_review_service_container_asks_to_start_compose(self):
        compose = FakeCompose(statuses=("",))

        with self.assertRaisesRegex(LocalImportError, "docker compose up"):
            wait_for_review_service(compose, 60, self.clock.sleep, self.clock)

    def test_timeout_points_to_the_reset_option(self):
        compose = FakeCompose(ready_answers=("0",))

        with self.assertRaisesRegex(LocalImportError, "--reset-review-schema"):
            wait_for_review_service(compose, 12, self.clock.sleep, self.clock)

    def test_reset_recreates_schema_with_previous_owner_and_restarts_service(self):
        compose = FakeCompose()

        reset_review_schema(compose)

        reset_sql = compose.calls[0][1]
        self.assertIn("DROP SCHEMA IF EXISTS review_service CASCADE", reset_sql)
        self.assertIn("AUTHORIZATION %I', coalesce(previous_owner, current_user)", reset_sql)
        self.assertEqual(compose.calls[1][0], ["docker", "compose", "restart", "review-service"])

    def test_import_does_not_touch_the_schema_without_the_reset_flag(self):
        self.write_reviews([self.review(1)])
        compose = FakeCompose(imported="1")

        self.assertEqual(self.run_main(compose), 0)

        self.assertFalse(any("DROP SCHEMA" in sql for sql in compose.sql_sent()))
        self.assertFalse(any(command[:3] == ["docker", "compose", "restart"] for command, _ in compose.calls))

    def test_invalid_reviews_are_skipped_by_default_and_rejected_in_strict_mode(self):
        self.write_reviews([self.review(1), self.review(2, content=" ")])

        self.assertEqual(self.run_main(FakeCompose(imported="1")), 0)
        self.assertEqual(self.run_main(FakeCompose(), "--strict"), 1)

    def test_missing_input_fails_before_calling_docker(self):
        compose = FakeCompose()

        result = main(["--input", str(self.root / "missing")], runner=compose)

        self.assertEqual(result, 1)
        self.assertEqual(compose.calls, [])

    def test_gateway_check_retries_while_review_service_is_not_registered(self):
        self.write_reviews([self.review(1), self.review(2)])
        answers = [HTTPError("url", 503, "Service Unavailable", None, None), FakeResponse(b'{"totalElements": 2}')]

        def opener(url, timeout):
            self.assertIn("productId=123", url)
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        self.assertEqual(self.run_main(FakeCompose(), opener=opener), 0)
        self.assertEqual(answers, [])

    def test_psql_failure_is_reported_as_an_error(self):
        self.write_reviews([self.review(1)])

        def failing(command, stdin_text):
            return completed(returncode=1, stderr='service "postgres" is not running')

        self.assertEqual(self.run_main(failing), 1)


if __name__ == "__main__":
    unittest.main()
