import json
from types import SimpleNamespace

import pytest

from scripts import repo_skill_study as study
from scripts.repo_calibration import COLLECTION, save
from scripts.repo_workspace import Workspace


def test_plan_has_fresh_balanced_conditions_and_screen_requires_valid_controls(monkeypatch):
    monkeypatch.setattr(study, "preflight", lambda _: "test-image")
    plan = study.make_plan("unused")
    assert len(plan["runs"]) == 36 and len(plan["conditions"]) == 12
    assert set(job["task"] for job in plan["runs"]) == {"dotenv-backslash"}
    assert len({job["id"] for job in plan["runs"]}) == 36
    rows = []
    for job in plan["runs"]:
        passed = job["condition"] not in ("all", "all-reversed")
        status = "passed" if passed else "failed"
        rows.append(
            {
                "job": job,
                "result": {
                    "status": status,
                    "grading": {"status": status, "tests": 13},
                    "calls_attempted": 10,
                    "reported_tokens": {"total_tokens": 20},
                },
            }
        )
    report = study.comparison_report(plan, rows)
    assert report["candidate_screen"]["candidates"] == ["all", "all-reversed"]
    neutral = next(row for row in rows if row["job"]["condition"] == "length-a")
    neutral["result"] = {**neutral["result"], "status": "api_error", "grading": None}
    assert study.comparison_report(plan, rows)["candidate_screen"]["candidates"] == []


@pytest.mark.parametrize(
    "failure, expected, count",
    [
        (None, "completed", 4),
        ("usage", "unknown_usage_stopped", 1),
        ("budget", "budget_stopped", 1),
    ],
)
def test_scheduler_preserves_order_and_stops_before_unreserved_calls(
    tmp_path, monkeypatch, failure, expected, count
):
    task = COLLECTION / "dotenv-backslash/task.json"
    plan = {
        "runs": [
            {"id": f"trial-{i}", "task": study.TASK, "condition": "baseline", "repeat": i}
            for i in range(4)
        ],
        "skills": [],
        "conditions": [{"id": "baseline", "policy": "global", "skill_ids": [], "control": "none"}],
        "workspace_sha256": {study.TASK: Workspace(task).initial_fingerprint},
        "budget": {"max_requests": 40, "max_estimated_usd": 0.23 if failure == "budget" else 3.0},
    }
    path = tmp_path / "plan.json"
    save(path, plan)
    monkeypatch.setattr(study, "PLAN", path)
    monkeypatch.setattr(study, "WORKERS", 1 if failure else 2)
    monkeypatch.setattr(study, "make_plan", lambda _: plan)
    monkeypatch.setattr(study, "load_settings", lambda: SimpleNamespace(docker="unused"))
    monkeypatch.setattr(
        study.subprocess,
        "run",
        lambda command, **kwargs: SimpleNamespace(
            stdout=(json.dumps(plan).encode() if "show" in command else "test-commit\n")
        ),
    )
    calls = []

    def agent(task, settings, directory, *, skills, condition):
        calls.append(directory.name)
        assert skills == () and condition.id == "baseline"
        directory.mkdir(parents=True)
        result = {
            "status": "passed",
            "calls_attempted": 10,
            "usage_complete": failure != "usage",
            "estimated_usd_upper": 0.02,
        }
        save(directory / "run.json", result)
        return result

    monkeypatch.setattr(study, "run_agent", agent)
    output = tmp_path / "study"
    study.run(output)
    state = json.loads((output / "study.json").read_text())
    rows = json.loads((output / "results.json").read_text())
    assert state["status"] == expected
    assert len(calls) == len(rows) == count
    assert [row["job"] for row in rows] == plan["runs"][:count]
