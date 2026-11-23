import json

import pytest

from skillscope import runner
from skillscope.backend import RunError
from skillscope.sandbox import SandboxError
from skillscope.settings import Settings

CODE = "def clamp(value, lower, upper):\n    return value\n"


@pytest.fixture
def fake_run(monkeypatch):
    calls, grades = [], []

    class Backend:
        def __init__(self, *args):
            pass

        def close(self):
            pass

        def redact(self, value):
            return value

        def complete(self, model, stage, messages, record):
            calls.append((stage, messages))
            record(
                {
                    "type": "response",
                    "response": {
                        "model": "fixed-version",
                        "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
                    },
                }
            )
            return CODE if stage == "implement" else "Short handoff."

    def grade(*args):
        grades.append(args)
        return {"status": "passed", "passed": True, "tests": 9}

    monkeypatch.setattr(runner, "DeepSeekBackend", Backend)
    monkeypatch.setattr(runner, "preflight", lambda _: "sha256:test-image")
    monkeypatch.setattr(runner, "grade", grade)
    return calls, grades


def test_graph_rebuilds_phase_inputs_then_scores_submitted_code(config, tmp_path, fake_run):
    calls, grades = fake_run
    output = tmp_path / "run"
    result = runner.run_task(config, "clamp", "scoped", Settings(api_key="test-secret"), output)
    assert [stage for stage, _ in calls] == ["investigate", "implement", "verify"]
    assert "Skill guide: root-cause" in calls[0][1][0]["content"]
    assert "Skill guide: root-cause" not in calls[1][1][0]["content"]
    assert "Skill guide: minimal-fix" in calls[1][1][0]["content"]
    assert "Skill guide:" not in calls[2][1][0]["content"]
    assert all(len(messages) == 2 for _, messages in calls)
    assert CODE in calls[2][1][-1]["content"]
    assert grades[0][0] == CODE
    assert result["status"] == "passed"
    assert result["reported_tokens"]["total_tokens"] == 30
    assert result["calls_attempted"] == 3 and result["usage_complete"]
    assert json.loads((output / "run.json").read_text())["grading"]["tests"] == 9
    assert "test-secret" not in (output / "trace.jsonl").read_text()


def test_budget_exhaustion_does_not_grade_or_make_extra_calls(config, tmp_path, fake_run):
    calls, grades = fake_run
    result = runner.run_task(
        config, "clamp", "baseline", Settings(api_key="test-secret"), tmp_path / "run", max_calls=1
    )
    assert result["status"] == "budget_exhausted"
    assert result["calls_attempted"] == len(calls) == 1
    assert not grades


def test_holdout_and_existing_output_fail_before_paid_requests(config, tmp_path, fake_run):
    calls, _ = fake_run
    settings = Settings(api_key="test-secret")
    with pytest.raises(ValueError, match="Holdout"):
        runner.run_task(config, "deduplicate", "baseline", settings, tmp_path / "holdout")
    with pytest.raises(FileExistsError):
        runner.run_task(config, "clamp", "baseline", settings, tmp_path)
    assert not calls


def test_docker_preflight_failure_prevents_model_requests(config, tmp_path, fake_run, monkeypatch):
    calls, _ = fake_run

    def unavailable(_):
        raise SandboxError("engine unavailable")

    monkeypatch.setattr(runner, "preflight", unavailable)
    output = tmp_path / "no-run"
    with pytest.raises(SandboxError):
        runner.run_task(config, "clamp", "baseline", Settings(api_key="test-secret"), output)
    assert not calls and not output.exists()


def test_failed_provider_request_has_no_grade_or_invented_usage(
    config, tmp_path, fake_run, monkeypatch
):
    _, grades = fake_run

    def fail(*args):
        raise RunError("api_error", "DeepSeek HTTP 402")

    monkeypatch.setattr(runner.DeepSeekBackend, "complete", fail)
    result = runner.run_task(
        config, "clamp", "baseline", Settings(api_key="test-secret"), tmp_path / "failed-call"
    )
    assert result["status"] == "api_error"
    assert result["calls_attempted"] == 1
    assert result["responses_received"] == 0
    assert not result["usage_complete"]
    assert result["grading"] is None and result["cost"] is None and not grades


def test_invalid_syntax_stops_before_review_and_grading(config, tmp_path, fake_run, monkeypatch):
    calls, grades = fake_run
    original = runner.DeepSeekBackend.complete

    def invalid(self, model, stage, messages, record):
        value = original(self, model, stage, messages, record)
        return "def broken(" if stage == "implement" else value

    monkeypatch.setattr(runner.DeepSeekBackend, "complete", invalid)
    result = runner.run_task(
        config, "clamp", "baseline", Settings(api_key="test-secret"), tmp_path / "syntax-error"
    )
    assert result["status"] == "invalid_output"
    assert [stage for stage, _ in calls] == ["investigate", "implement"]
    assert not grades
