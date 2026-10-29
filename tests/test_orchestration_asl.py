import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
ASL = json.loads((ROOT / "infra/data-pipeline/orchestration.asl.json").read_text(encoding="utf-8"))
STATES = ASL["States"]


class CfnLoader(yaml.SafeLoader):
    """Read CloudFormation short-form tags such as !Ref as plain values."""


CfnLoader.add_multi_constructor("!", lambda loader, suffix, node: None)


def transitions(state):
    targets = [state.get("Next"), state.get("Default")]
    targets += [choice.get("Next") for choice in state.get("Choices", [])]
    targets += [catch.get("Next") for catch in state.get("Catch", [])]
    return [target for target in targets if target]


def test_every_transition_points_to_a_defined_state():
    assert ASL["StartAt"] in STATES
    for name, state in STATES.items():
        for target in transitions(state):
            assert target in STATES, f"{name} -> {target}"
        if state["Type"] not in {"Choice", "Fail", "Succeed"}:
            assert ("Next" in state) != bool(state.get("End")), name


def test_every_state_is_reachable():
    seen, pending = set(), [ASL["StartAt"]]
    while pending:
        name = pending.pop()
        if name not in seen:
            seen.add(name)
            pending.extend(transitions(STATES[name]))
    assert seen == set(STATES)


def test_pipeline_stages_record_failures():
    for name, state in STATES.items():
        if state["Type"] == "Task" and name not in {"RecordSuccess", "RecordFailure"}:
            assert any(catch["Next"] in {"RecordFailure", "PipelineFailed"} for catch in state["Catch"]), name


def test_long_running_jobs_are_polled_by_the_state_machine():
    for runner, check, wait in (
        ("RunCrawler", "CheckCrawlerJob", "WaitForCrawlerJob"),
        ("RunFashionClip", "CheckFashionClipJob", "WaitForFashionClipJob"),
    ):
        assert STATES[runner]["Next"] == check
        assert STATES[check]["Choices"][0] == {"Variable": "$.job_status", "StringEquals": "SUCCEEDED", "Next": STATES[check]["Choices"][0]["Next"]}
        assert STATES[check]["Default"] == wait
        assert STATES[wait]["Next"] == runner
        assert STATES[runner]["Retry"][0] == {"ErrorEquals": ["JobNotStartedError"], "MaxAttempts": 0}


def test_definition_placeholders_match_stack_substitutions():
    text = (ROOT / "infra/data-pipeline/orchestration.asl.json").read_text(encoding="utf-8")
    placeholders = set(re.findall(r"\$\{(\w+)\}", text))
    template = yaml.load((ROOT / "infra/aws/cloudformation/orchestration.yaml").read_text(encoding="utf-8"), Loader=CfnLoader)
    substitutions = template["Resources"]["PipelineStateMachine"]["Properties"]["DefinitionSubstitutions"]
    assert placeholders == set(substitutions)


def test_schedules_stay_disabled_by_default():
    template = yaml.load((ROOT / "infra/aws/cloudformation/orchestration.yaml").read_text(encoding="utf-8"), Loader=CfnLoader)
    assert template["Parameters"]["ScheduleState"]["Default"] == "DISABLED"


def test_placeholder_stage_failures_are_not_retried():
    for name in ("RunIntegrityChecks", "ValidateAndImport", "RunJev"):
        assert STATES[name]["Retry"][0] == {"ErrorEquals": ["StageNotEnabledError"], "MaxAttempts": 0}


def test_human_review_waits_on_a_task_token_and_fails_closed():
    state = STATES["WaitForHumanReview"]

    assert STATES["RunJev"]["Next"] == "WaitForHumanReview"
    assert state["Resource"] == "arn:aws:states:::lambda:invoke.waitForTaskToken"
    assert state["Parameters"]["Payload"] == {"contract.$": "$", "task_token.$": "$$.Task.Token"}
    assert state["ResultPath"] == "$.review"
    assert state["Next"] == "RunFashionClip"
    assert state["Catch"][0] == {"ErrorEquals": ["States.ALL"], "ResultPath": "$.failure", "Next": "RecordFailure"}
    assert all("States.Timeout" not in retry["ErrorEquals"] for retry in state["Retry"])
    assert not any(other["Type"] == "Wait" and other["Next"] == "WaitForHumanReview" for other in STATES.values())
