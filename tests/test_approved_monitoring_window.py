from datetime import datetime, timedelta, timezone
import json
import os
import types
import unittest
from unittest.mock import Mock, patch

from scripts.configure_approved_monitoring_window import main, proposed_code, schedule_specs

KST = timezone(timedelta(hours=9))


class ApprovedMonitoringWindowTests(unittest.TestCase):
    def call(self, moment, event):
        client = Mock()
        client.update_nodegroup_config.return_value = {
            "update": {"id": "test", "status": "InProgress"}
        }
        boto = types.SimpleNamespace(client=Mock(return_value=client))
        runtime = {}
        with patch.dict("sys.modules", {"boto3": boto}):
            exec(compile(proposed_code(), "node_scaler.py", "exec"), runtime)
        runtime["datetime"] = Mock(
            now=Mock(return_value=datetime.fromisoformat(moment).replace(tzinfo=KST))
        )
        with patch.dict(
            os.environ,
            {
                "BLOCKED_SCALE_UP_DATES": "2026-10-19,2026-10-26",
                "CLUSTER_NAME": "test",
                "NODE_GROUP_NAME": "test",
            },
        ):
            result = runtime["handler"](event, None)
        return result, client

    def test_exact_window_allows_scale_up(self):
        for time, permitted in (
            ("11:59:59", False),
            ("12:00:00", True),
            ("22:59:59", True),
            ("23:00:00", False),
        ):
            with self.subTest(time=time):
                result, client = self.call(f"2026-11-01T{time}", {"desiredSize": 1})
                self.assertEqual(client.update_nodegroup_config.called, permitted)
                if not permitted:
                    self.assertEqual(result["status"], "SKIPPED")

    def test_shutdown_is_always_allowed(self):
        _, client = self.call("2026-11-01T23:00:00", {"desiredSize": 0})
        client.update_nodegroup_config.assert_called_once()
        self.assertEqual(
            client.update_nodegroup_config.call_args.kwargs["scalingConfig"],
            {"minSize": 0, "maxSize": 1, "desiredSize": 0},
        )

    def test_two_one_time_schedules_preserve_target(self):
        target = {"Arn": "lambda-arn", "RoleArn": "existing-role", "Input": "old"}
        specs = schedule_specs(target)
        self.assertEqual(len(specs), 2)
        expected_sizes = {
            "at(2026-11-01T12:00:00)": 1,
            "at(2026-11-01T23:00:00)": 0,
        }
        for spec in specs:
            self.assertEqual(spec["ScheduleExpressionTimezone"], "Asia/Seoul")
            self.assertEqual(spec["ActionAfterCompletion"], "DELETE")
            self.assertEqual(spec["Target"]["Arn"], "lambda-arn")
            self.assertEqual(spec["Target"]["RoleArn"], "existing-role")
            self.assertEqual(
                json.loads(spec["Target"]["Input"])["desiredSize"],
                expected_sizes[spec["ScheduleExpression"]],
            )
        self.assertEqual(target["Input"], "old")

    def test_default_makes_no_aws_calls(self):
        with patch("sys.argv", ["configure_window"]), patch("boto3.Session") as session:
            main()
            session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
