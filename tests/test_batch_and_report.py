import json
from dataclasses import replace
from pathlib import Path
from shutil import copytree

import pytest

from skillscope import batch
from skillscope.loader import load_experiment
from skillscope.models import Stage
from skillscope.planner import build_plan, conditions_for
from skillscope.prompts import build_messages
from skillscope.report import build_report, summarize, wilson
from skillscope.settings import Settings


@pytest.fixture
def stage3_config(tmp_path):
    source = Path(__file__).resolve().parents[1] / "benchmarks/stage3"
    copytree(source, tmp_path / "corpus")
    return tmp_path / "corpus/experiment.json"


@pytest.fixture
def fake_batch(monkeypatch):
    calls = []
    behavior = {"status": "passed", "usage_complete": True}
    monkeypatch.setattr(batch, "preflight", lambda _: "test-image")
    monkeypatch.setattr(batch, "source_fingerprint", lambda: "test-source")

    def run(config, task, condition, settings, output, **kwargs):
        calls.append((task, condition))
        output.mkdir(parents=True)
        result = {
            "experiment_sha256": load_experiment(config).sha256,
            "sandbox_image_id": "test-image",
            "status": behavior["status"],
            "calls_attempted": 3,
            "reported_tokens": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
            "usage_complete": behavior["usage_complete"],
        }
        batch.write_json(output / "run.json", result)
        return result

    monkeypatch.setattr(batch, "run_task", run)
    return calls, behavior


def test_stage3_matrix_has_all_controls_and_no_holdout(stage3_config):
    experiment = load_experiment(stage3_config)
    plan = build_plan(experiment, controls=True)
    assert len(experiment.skills) == 6
    assert len(plan["conditions"]) == 12 and plan["run_count"] == 144
    assert {task["id"] for task in plan["tasks"]} == {
        "clamp",
        "get-path",
        "merge-intervals",
        "toposort",
    }
    assert not any(run["task_id"] in ("deduplicate", "parse-duration") for run in plan["runs"])


def test_control_prompts_match_characters_and_reverse_real_order(stage3_config):
    experiment = load_experiment(stage3_config)
    conditions = {item.id: item for item in conditions_for(experiment, controls=True)}
    real = build_messages(experiment, "clamp", conditions["all"], Stage.IMPLEMENT)
    for name in ("length-a", "length-b"):
        control = build_messages(experiment, "clamp", conditions[name], Stage.IMPLEMENT)
        assert len(real[0]["content"]) == len(control[0]["content"])
        assert real[1] == control[1]
        assert "Trace a failing example" not in control[0]["content"]
    assert conditions["all-reversed"].skill_ids == tuple(reversed(conditions["all"].skill_ids))


def test_complete_batch_resume_and_report_do_not_make_duplicate_calls(
    stage3_config, tmp_path, fake_batch
):
    calls, _ = fake_batch
    output = tmp_path / "batch"
    settings = Settings(api_key="test-secret")
    result = batch.run_batch(stage3_config, settings, output)
    assert result["status"] == "completed" and result["completed"] == 148
    assert len(calls) == 148
    assert sum(condition == "baseline" for _, condition in calls) == 16
    batch.run_batch(stage3_config, settings, output, resume=True)
    assert len(calls) == 148
    report = build_report(output)
    assert report["main_runs_recorded"] == 144 and report["pilot_runs"] == 4
    assert report["groups"]["all"]["successes"] == 12
    assert report["groups"]["all"]["calls"] == 36
    assert report["missing_outcomes"] == 0
    assert not report["candidate_combinations"]
    assert not (output / ".active").exists()


def test_budget_reservation_stops_before_spending(stage3_config, tmp_path, fake_batch):
    calls, _ = fake_batch
    result = batch.run_batch(
        stage3_config,
        Settings(api_key="test-secret"),
        tmp_path / "batch",
        replace(batch.Limits(), max_estimated_usd=0.001),
    )
    assert result["stop_reason"] == "budget_reservation_limit" and not calls


def test_failed_baseline_gate_prevents_main_experiments(stage3_config, tmp_path, fake_batch):
    calls, behavior = fake_batch
    behavior["status"] = "failed"
    result = batch.run_batch(stage3_config, Settings(api_key="test-secret"), tmp_path / "batch")
    assert result["stop_reason"] == "baseline_gate_failed"
    assert len(calls) == 4 and all(condition == "baseline" for _, condition in calls)


def test_unknown_usage_stops_new_requests_and_resume_never_retries(
    stage3_config, tmp_path, fake_batch
):
    calls, behavior = fake_batch
    behavior.update(status="api_error", usage_complete=False)
    output = tmp_path / "batch"
    result = batch.run_batch(stage3_config, Settings(api_key="test-secret"), output)
    assert result["status"] == "stopped" and len(calls) <= 3
    count = len(calls)
    batch.run_batch(stage3_config, Settings(api_key="test-secret"), output, resume=True)
    assert len(calls) == count


def test_resume_rejects_changed_frozen_inputs(stage3_config, tmp_path, fake_batch):
    output = tmp_path / "batch"
    batch.run_batch(
        stage3_config,
        Settings(api_key="test-secret"),
        output,
        replace(batch.Limits(), max_estimated_usd=0.001),
    )
    path = output / "frozen/skills/root-cause.md"
    path.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="Frozen input"):
        batch.run_batch(
            stage3_config,
            Settings(api_key="test-secret"),
            output,
            replace(batch.Limits(), max_estimated_usd=0.001),
            resume=True,
        )


def test_estimates_use_cache_usage_and_peak_prices():
    assert batch.estimate_cost(
        {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000}
    ) == pytest.approx(1.5)
    assert batch.estimate_cost({"prompt_tokens": 1_000_000}, cache_hits=1_000_000) == pytest.approx(
        0.006
    )


def test_uncertainty_and_unknown_errors_do_not_become_model_failures():
    rows = [
        {
            "status": status,
            "calls_attempted": 3,
            "reported_tokens": {"total_tokens": 20},
            "estimated_usd_upper": 0.001,
        }
        for status in ("passed", "failed", "api_error", "invalid_output")
    ]
    result = summarize(rows, planned=5)
    assert result["known_model_outcomes"] == 3 and result["unknown_or_missing"] == 2
    assert result["completion_rate_known"] == pytest.approx(1 / 3)
    assert result["completion_bounds_missing"] == [0.2, 0.6]
    assert wilson(0, 0) is None
    assert wilson(0, 12)[0] == pytest.approx(0)
    assert wilson(12, 12)[0] == pytest.approx(0.75750599)
    assert wilson(12, 12)[1] == pytest.approx(1)


def test_report_flags_repeated_regression_as_candidate_only(stage3_config, tmp_path, fake_batch):
    output = tmp_path / "batch"
    batch.run_batch(stage3_config, Settings(api_key="test-secret"), output)
    path = output / "results.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        if (
            row["job"]["phase"] == "main"
            and row["job"]["task_id"] == "toposort"
            and row["job"]["condition_id"] == "all"
        ):
            row["status"] = "failed"
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    report = build_report(output)
    assert len(report["candidate_combinations"]) == 1
    assert report["candidate_combinations"][0]["task"] == "toposort"
    assert report["candidate_combinations"][0]["length_controls_all_pass"]
    assert report["conclusion"] == "repeated_regression_candidates_require_confirmation"
