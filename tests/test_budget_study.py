import json
from collections import Counter
from pathlib import Path

import pytest

from scripts import budget_study
from skillscope.loader import load_experiment
from skillscope.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "benchmarks/stage3/experiment.json"


def test_plan_is_balanced_frozen_and_reproducibly_shuffled():
    plan = budget_study.make_plan()
    assert len(plan["runs"]) == 40
    assert len({job["id"] for job in plan["runs"]}) == 40
    counts = Counter((job["condition_id"], job["cap"]) for job in plan["runs"])
    assert len(counts) == 8 and set(counts.values()) == {5}
    assert plan == budget_study.make_plan(seed=1041)
    assert plan["runs"] != budget_study.make_plan(seed=1042)["runs"]
    assert all(job["task_id"] == "get-path" for job in plan["runs"])


@pytest.fixture
def fake_runner(monkeypatch):
    calls = []
    options = {"low_reverse_truncation": False, "external_error": False}
    monkeypatch.setattr(budget_study, "preflight", lambda _: "test-image")

    def run(config, task, condition, settings, output, max_tokens, **kwargs):
        calls.append((task, condition, max_tokens))
        output.mkdir(parents=True)
        truncated = (
            options["low_reverse_truncation"] and condition == "all-reversed" and max_tokens == 1024
        )
        status = (
            "api_error"
            if options["external_error"]
            else ("invalid_output" if truncated else "passed")
        )
        result = {
            "status": status,
            "sandbox_image_id": "test-image",
            "experiment_sha256": load_experiment(config).sha256,
            "calls_attempted": 1 if truncated or options["external_error"] else 3,
            "reported_tokens": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            "usage_complete": not options["external_error"],
        }
        event = {
            "type": "response",
            "response": {
                "choices": [{"finish_reason": "length" if truncated else "stop"}],
                "usage": result["reported_tokens"],
            },
        }
        (output / "trace.jsonl").write_text(json.dumps(event) + "\n", encoding="utf-8")
        (output / "run.json").write_text(json.dumps(result), encoding="utf-8")
        return result

    monkeypatch.setattr(budget_study, "run_task", run)
    return calls, options


def test_execution_passes_correct_caps_and_preserves_original_data(tmp_path, fake_runner):
    calls, _ = fake_runner
    before = load_experiment(CONFIG).sha256
    output = tmp_path / "study"
    result = budget_study.execute(CONFIG, Settings(api_key="test-secret"), output, repeats=2)
    assert result["status"] == "completed" and result["completed"] == 16
    assert len(calls) == 16 and {cap for _, _, cap in calls} == {1024, 2048}
    assert before == load_experiment(CONFIG).sha256
    assert load_experiment(output / "frozen/experiment.json").sha256 == before
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert not report["observed_budget_sensitive_candidates"]
    assert all(
        group["passed"] == 2 and group["unknown"] == 0 for group in report["groups"].values()
    )
    with pytest.raises(FileExistsError):
        budget_study.execute(CONFIG, Settings(api_key="test-secret"), output, repeats=2)
    assert len(calls) == 16


def test_truncations_are_retained_and_labeled_only_as_candidates(tmp_path, fake_runner):
    _, options = fake_runner
    options["low_reverse_truncation"] = True
    output = tmp_path / "study"
    result = budget_study.execute(CONFIG, Settings(api_key="test-secret"), output, repeats=2)
    assert result["status"] == "completed"
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["groups"]["all-reversed/1024"]["length_truncations"] == 2
    assert report["groups"]["all-reversed/2048"]["passed"] == 2
    assert report["observed_budget_sensitive_candidates"] == ["all-reversed"]


def test_unknown_usage_stops_new_paid_work(tmp_path, fake_runner):
    calls, options = fake_runner
    options["external_error"] = True
    result = budget_study.execute(
        CONFIG, Settings(api_key="test-secret"), tmp_path / "study", repeats=2
    )
    assert result["status"] == "stopped"
    assert result["stop_reason"] == "unknown_usage_or_external_failure"
    assert len(calls) <= 2
