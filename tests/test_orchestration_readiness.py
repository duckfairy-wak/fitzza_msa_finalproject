import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


class CfnLoader(yaml.SafeLoader):
    """Read CloudFormation short-form tags such as !Ref as plain values."""


CfnLoader.add_multi_constructor("!", lambda loader, suffix, node: None)


def test_parameters_example_matches_the_stack():
    template = yaml.load((ROOT / "infra/aws/cloudformation/orchestration.yaml").read_text(encoding="utf-8"), Loader=CfnLoader)
    example = json.loads((ROOT / "infra/aws/cloudformation/orchestration-parameters.example.json").read_text(encoding="utf-8"))
    values = {item["ParameterKey"]: item["ParameterValue"] for item in example}

    assert set(values) == set(template["Parameters"])
    assert values["ScheduleState"] == "DISABLED"
    assert values["EnableReviewNotification"] == "false"
    assert values["EnableApprovalEvents"] == "false"


def test_example_schedules_fall_inside_the_default_run_window():
    example = json.loads((ROOT / "infra/aws/cloudformation/orchestration-parameters.example.json").read_text(encoding="utf-8"))
    values = {item["ParameterKey"]: item["ParameterValue"] for item in example}
    for key in ("ScheduleExpression", "WeeklyScheduleExpression"):
        minute, hour, _, _, days, _ = re.fullmatch(r"cron\((.+)\)", values[key])[1].split()
        kst_minutes = (int(hour) + 9) % 24 * 60 + int(minute)
        assert 9 * 60 + 30 <= kst_minutes < 16 * 60, key
        assert not set(days.split(",")) & {"SAT", "SUN"}, key


def test_color_dictionary_palette_matches_the_review_gate():
    schema = json.loads((ROOT / "infra/data-pipeline/color-dictionary.schema.json").read_text(encoding="utf-8"))
    gate = (ROOT / "infra/data-pipeline/crawler/src/review_gate.py").read_text(encoding="utf-8")
    colors = set(re.findall(r'"([a-z]+)"', gate[gate.index("COLORS = {"):gate.index("}", gate.index("COLORS = {"))]))

    assert set(schema["$defs"]["entry"]["properties"]["color"]["enum"]) == colors


def test_color_dictionary_example_uses_known_colors_and_versions():
    schema = json.loads((ROOT / "infra/data-pipeline/color-dictionary.schema.json").read_text(encoding="utf-8"))
    example = json.loads((ROOT / "infra/data-pipeline/color-dictionary.example.json").read_text(encoding="utf-8"))
    entry = schema["$defs"]["entry"]

    assert set(example) == set(schema["required"])
    assert re.fullmatch(schema["properties"]["dictionary_version"]["pattern"], example["dictionary_version"])
    for value in example["colors"].values():
        assert set(value) == set(entry["required"])
        assert value["color"] in entry["properties"]["color"]["enum"]
        assert value["basis"] in entry["properties"]["basis"]["enum"]


def test_job_role_cannot_upload_approved_bundles():
    template = (ROOT / "infra/aws/cloudformation/orchestration.yaml").read_text(encoding="utf-8")
    block = template[template.index("  PipelineJobRole:\n"):template.index("  PipelineJobPodIdentity:\n")]
    assert "Sid: DenyApprovedBundleWrites\n                Effect: Deny\n                Action: s3:PutObject" in block
    assert "/pipeline/runs/*/approved/*'" in block


def test_template_default_schedules_match_the_example_and_run_window():
    template = yaml.load((ROOT / "infra/aws/cloudformation/orchestration.yaml").read_text(encoding="utf-8"), Loader=CfnLoader)
    example = json.loads((ROOT / "infra/aws/cloudformation/orchestration-parameters.example.json").read_text(encoding="utf-8"))
    values = {item["ParameterKey"]: item["ParameterValue"] for item in example}
    for key in ("ScheduleExpression", "WeeklyScheduleExpression"):
        assert template["Parameters"][key]["Default"] == values[key], key
