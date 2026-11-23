import json

import pytest

from skillscope.models import Condition, Stage
from skillscope.planner import build_plan, conditions_for
from skillscope.prompts import build_messages


def test_plan_contains_balanced_repeats_and_no_holdout_leak(experiment):
    plan = build_plan(experiment, repeats=3)
    assert plan["run_count"] == 15
    assert len({run["id"] for run in plan["runs"]}) == 15
    for condition in conditions_for(experiment):
        assert sorted(
            run["repeat"] for run in plan["runs"] if run["condition_id"] == condition.id
        ) == [1, 2, 3]
    assert {task["id"] for task in plan["tasks"]} == {"clamp"}
    assert {run["task_id"] for run in plan["runs"]} == {"clamp"}
    assert "deduplicate" not in json.dumps(plan)
    assert plan["status"] == "planned_not_executed"
    assert "scores" not in plan


def test_holdout_requires_explicit_selection(experiment):
    plan = build_plan(experiment, split="holdout")
    assert {task["id"] for task in plan["tasks"]} == {"deduplicate"}
    assert {run["task_id"] for run in plan["runs"]} == {"deduplicate"}


def test_schedule_seed_controls_order_only(experiment):
    first = build_plan(experiment, seed=42)
    assert first == build_plan(experiment, seed=42)
    other = build_plan(experiment, seed=43)
    assert first["runs"] != other["runs"]
    assert {run["id"] for run in first["runs"]} == {run["id"] for run in other["runs"]}


@pytest.mark.parametrize("kwargs", [{"repeats": 0}, {"max_runs": 14}, {"split": "typo"}])
def test_invalid_or_excessive_plans_fail_before_materializing(experiment, kwargs):
    with pytest.raises(ValueError):
        build_plan(experiment, **kwargs)


@pytest.mark.parametrize(
    "stage,expected,absent",
    [
        (Stage.INVESTIGATE, "root-cause", "minimal-fix"),
        (Stage.IMPLEMENT, "minimal-fix", "root-cause"),
    ],
)
def test_scoped_input_contains_only_current_phase_skill(experiment, stage, expected, absent):
    scoped = next(item for item in conditions_for(experiment) if item.id == "scoped")
    messages = build_messages(experiment, "clamp", scoped, stage)
    assert f"--- Skill guide: {expected} ---" in messages[0]["content"]
    assert f"--- Skill guide: {absent} ---" not in messages[0]["content"]


def test_verification_input_does_not_retain_previous_phase_messages(experiment):
    scoped = next(item for item in conditions_for(experiment) if item.id == "scoped")
    old = build_messages(experiment, "clamp", scoped, Stage.INVESTIGATE)
    old.append({"role": "assistant", "content": "old-phase-canary"})
    current = build_messages(experiment, "clamp", scoped, Stage.VERIFY)
    assert "Skill guide:" not in current[0]["content"]
    assert "old-phase-canary" not in json.dumps(current)
    assert len(current) == 2


@pytest.mark.parametrize("stage", list(Stage))
def test_all_condition_preserves_both_guides_in_all_phases(experiment, stage):
    condition = next(item for item in conditions_for(experiment) if item.id == "all")
    system = build_messages(experiment, "clamp", condition, stage)[0]["content"]
    assert system.index("--- Skill guide: root-cause") < system.index(
        "--- Skill guide: minimal-fix"
    )


def test_explicit_skill_order_is_preserved(experiment):
    condition = Condition(id="reversed", policy="global", skill_ids=("minimal-fix", "root-cause"))
    system = build_messages(experiment, "clamp", condition, Stage.INVESTIGATE)[0]["content"]
    assert system.index("--- Skill guide: minimal-fix") < system.index(
        "--- Skill guide: root-cause"
    )


def test_baseline_has_no_guides_and_task_is_identical_across_conditions(experiment):
    messages = [
        build_messages(experiment, "clamp", condition, Stage.INVESTIGATE)
        for condition in conditions_for(experiment)
    ]
    assert "Skill guide:" not in messages[0][0]["content"]
    assert all(item[1] == messages[0][1] for item in messages)
    assert all("import pytest" not in item[1]["content"] for item in messages)


@pytest.mark.parametrize("ids", [("unknown",), ("root-cause", "root-cause")])
def test_invalid_conditions_fail_instead_of_silently_ignoring_skills(experiment, ids):
    condition = Condition(id="invalid", policy="global", skill_ids=ids)
    with pytest.raises(ValueError):
        build_messages(experiment, "clamp", condition, Stage.INVESTIGATE)
