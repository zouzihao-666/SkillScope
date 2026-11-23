import hashlib
import json
from pathlib import Path
from shutil import copytree

import pytest

from skillscope.batch import write_json
from skillscope.models import Stage
from skillscope.presentation import workflow_report
from skillscope.settings import Settings
from skillscope.workflow import DiagnosisWorkflow, full_policy, prepare

FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks/repo-prototype/cart"


@pytest.fixture
def diagnosis_config(tmp_path):
    tasks = []
    for name, split in (("discovery", "discovery"), ("holdout", "holdout")):
        target = tmp_path / name
        copytree(FIXTURE, target)
        manifest = json.loads((target / "task.json").read_text())
        manifest["id"] = name
        write_json(target / "task.json", manifest)
        tasks.append({"id": name, "split": split, "manifest": f"{name}/task.json"})
    skills = []
    for name, stage in (("good", "investigate"), ("bad", "verify"), ("other", "implement")):
        (tmp_path / f"{name}.md").write_text(f"{name} guidance.", encoding="utf-8")
        skills.append({"id": name, "file": f"{name}.md", "stages": [stage]})
    config = tmp_path / "diagnosis.json"
    write_json(
        config,
        {
            "name": "workflow-test",
            "skills": skills,
            "tasks": tasks,
            "validate_holdout": True,
            "limits": {"max_calls": 480, "max_runs": 48, "max_usd": 2},
        },
    )
    return config


@pytest.fixture
def oracle(monkeypatch):
    monkeypatch.setattr("skillscope.workflow.preflight", lambda *args: "test-image")
    calls = []

    def evaluate(task, settings, output, *, skills, condition, **kwargs):
        manifest = json.loads(task.read_text())
        calls.append((manifest["id"], output.name))
        root = output.parents[1]
        if manifest["id"] == "holdout":
            state = json.loads((root / "state.json").read_text())
            assert (
                state["policy_frozen_sha256"]
                == hashlib.sha256((root / "policy.json").read_bytes()).hexdigest()
            )
        output.mkdir(parents=True)
        active = {
            skill.id
            for skill in skills
            if skill.id in condition.skill_ids and Stage.IMPLEMENT in skill.stages
        }
        status = "failed" if "bad" in active else "passed"
        result = {
            "status": status,
            "grading": {"status": status, "tests": 9},
            "usage_complete": True,
            "calls_attempted": 1,
            "estimated_usd_upper": 0.001,
            "reported_tokens": {"total_tokens": 20},
            "source_sha256": json.loads((root / "plan.json").read_text())["source_sha256"],
            "initial_workspace_sha256": next(
                value["fingerprint"]
                for value in json.loads((root / "plan.json").read_text())["tasks"]
                if value["id"] == manifest["id"]
            ),
            "condition": condition.id,
        }
        write_json(output / "run.json", result)
        (output / "trace.jsonl").write_text(json.dumps({"type": "request"}) + "\n")
        return result

    return evaluate, calls


def test_complete_diagnosis_reduces_generates_selects_and_validates_frozen_policy(
    diagnosis_config, tmp_path, oracle
):
    evaluate, calls = oracle
    output = tmp_path / "run"
    workflow = prepare(
        diagnosis_config, output, Settings(api_key="unit-secret"), evaluator=evaluate
    )
    state = workflow.execute()
    assert state["status"] == "completed"
    diagnosis = state["diagnoses"]["discovery"]
    assert diagnosis["classification"] == "single_skill_regression"
    assert diagnosis["suspects"] == ["bad"]
    assert diagnosis["reduction"]["one_removal_minimal"]
    assert state["policy"]["method"] == "generated"
    assert "bad" not in state["policy"]["phases"]["implement"]
    assert "bad" in state["policy"]["phases"]["verify"]
    assert state["holdout_opened"] and state["holdout_validation"]
    count = len(calls)
    again = prepare(
        diagnosis_config, output, Settings(api_key="unit-secret"), resume=True, evaluator=evaluate
    )
    assert again.execute()["status"] == "completed" and len(calls) == count
    workflow_report(output)
    assert (output / "report.html").exists()


def test_identical_configurations_reuse_results_without_fake_independent_repeats(
    diagnosis_config, tmp_path, oracle
):
    evaluate, calls = oracle
    workflow = prepare(
        diagnosis_config, tmp_path / "cache", Settings(api_key="unit-secret"), evaluator=evaluate
    )
    task = workflow.plan["tasks"][0]
    first = workflow.measure(task, full_policy(()), "baseline")
    second = workflow.measure(task, full_policy(()), "same-policy")
    assert first == second and len(calls) == 3
    (entry,) = workflow.state["measurements"].values()
    assert entry["roles"] == ["baseline", "same-policy"]


def test_budget_stops_before_any_unreserved_call(diagnosis_config, tmp_path, oracle):
    evaluate, calls = oracle
    value = json.loads(diagnosis_config.read_text())
    value["limits"]["max_usd"] = 0.01
    write_json(diagnosis_config, value)
    workflow = prepare(
        diagnosis_config, tmp_path / "budget", Settings(api_key="unit-secret"), evaluator=evaluate
    )
    assert workflow.execute()["status"] == "budget_exhausted" and not calls


def test_unknown_usage_is_reserved_and_cannot_be_replayed_on_resume(
    diagnosis_config, tmp_path, oracle
):
    evaluate, calls = oracle

    def unknown(*args, **kwargs):
        result = evaluate(*args, **kwargs)
        return {
            **result,
            "usage_complete": False,
            "estimated_usd_upper": 0,
            "status": "api_error",
            "grading": None,
        }

    output = tmp_path / "unknown"
    workflow = prepare(diagnosis_config, output, Settings(api_key="unit-secret"), evaluator=unknown)
    state = workflow.execute()
    assert state["status"] == "unknown_usage_stopped"
    assert state["budget"]["unknown_reserved_usd"] == pytest.approx(workflow.reservation)
    assert len(calls) == 1
    resumed = prepare(
        diagnosis_config, output, Settings(api_key="unit-secret"), resume=True, evaluator=unknown
    )
    resumed.execute()
    assert len(calls) == 1 and not resumed.state["holdout_opened"]


def test_interrupted_reservation_and_holdout_gate_are_not_bypassed(
    diagnosis_config, tmp_path, oracle
):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()

    output = tmp_path / "interrupted"
    workflow = prepare(
        diagnosis_config, output, Settings(api_key="unit-secret"), evaluator=interrupted
    )
    with pytest.raises(ValueError, match="Holdout remains closed"):
        workflow.measure(workflow.plan["tasks"][1], full_policy(()), "forbidden")
    with pytest.raises(KeyboardInterrupt):
        workflow.execute()
    resumed = prepare(
        diagnosis_config,
        output,
        Settings(api_key="unit-secret"),
        resume=True,
        evaluator=interrupted,
    )
    assert resumed.execute()["status"] == "unknown_usage_stopped"
    assert resumed.budget()["unknown_reserved_usd"] == pytest.approx(resumed.reservation)


def test_plan_only_can_bind_an_image_before_its_first_execution(diagnosis_config, tmp_path, oracle):
    evaluate, calls = oracle
    output = tmp_path / "planned"
    planned = prepare(diagnosis_config, output, None, plan_only=True)
    assert planned.plan["image_id"] is None and not calls
    resumed = prepare(
        diagnosis_config, output, Settings(api_key="unit-secret"), resume=True, evaluator=evaluate
    )
    assert resumed.execute()["status"] == "completed"
    assert resumed.plan["image_id"] == "test-image"


def test_policy_file_tampering_stops_before_holdout(
    diagnosis_config, tmp_path, oracle, monkeypatch
):
    evaluate, calls = oracle
    original = DiagnosisWorkflow.freeze_policy

    def tampered(self):
        result = original(self)
        (self.root / "policy.json").write_text("{}")
        return result

    monkeypatch.setattr(DiagnosisWorkflow, "freeze_policy", tampered)
    workflow = prepare(
        diagnosis_config, tmp_path / "tampered", Settings(api_key="unit-secret"), evaluator=evaluate
    )
    with pytest.raises(ValueError, match="Frozen policy changed"):
        workflow.execute()
    assert all(task != "holdout" for task, _ in calls)


def test_lock_prevents_two_processes_from_owning_the_same_diagnosis(
    diagnosis_config, tmp_path, oracle
):
    from skillscope.workflow import workflow_lock

    evaluate, calls = oracle
    output = tmp_path / "locked"
    workflow = prepare(
        diagnosis_config, output, Settings(api_key="unit-secret"), evaluator=evaluate
    )
    with workflow_lock(output), pytest.raises(ValueError, match="already owns"):
        workflow.execute()
    assert not calls


def test_recovery_reuses_durable_results_after_a_lost_state_update(
    diagnosis_config, tmp_path, oracle
):
    evaluate, calls = oracle
    output = tmp_path / "recover"
    workflow = prepare(
        diagnosis_config, output, Settings(api_key="unit-secret"), evaluator=evaluate
    )
    task = workflow.plan["tasks"][0]
    workflow.measure(task, full_policy(()), "baseline")
    workflow.state["trials"][0].pop("result")
    workflow.state["trials"][0]["status"] = "reserved"
    workflow.state["measurements"] = {}
    workflow.state["status"] = "interrupted"
    workflow.save()
    result = prepare(
        diagnosis_config, output, Settings(api_key="unit-secret"), resume=True, evaluator=evaluate
    ).execute()
    assert result["status"] == "completed"
    first_ids = [id_ for _, id_ in calls[:3]]
    assert all(sum(id_ == other for _, other in calls) == 1 for id_ in first_ids)


def test_cli_plan_only_needs_no_key_and_holdout_requires_explicit_flag(
    diagnosis_config, tmp_path, monkeypatch
):
    from typer.testing import CliRunner

    from skillscope.cli import app

    monkeypatch.setattr(
        "skillscope.settings.load_settings",
        lambda *args: (_ for _ in ()).throw(AssertionError("No key or model access allowed")),
    )
    runner = CliRunner()
    output = tmp_path / "cli-plan"
    result = runner.invoke(
        app, ["diagnose", "--config", str(diagnosis_config), "--output", str(output), "--plan-only"]
    )
    assert result.exit_code == 0, result.output
    assert "模型调用：0" in result.output
    refused = runner.invoke(
        app,
        ["diagnose", "--config", str(diagnosis_config), "--output", str(tmp_path / "forbidden")],
    )
    assert refused.exit_code == 1 and "--allow-holdout" in refused.output


def test_export_and_html_report_are_complete_and_do_not_execute_model_text(
    diagnosis_config, tmp_path, oracle
):
    from skillscope.evidence import audited_files, export_workflow
    from skillscope.presentation import write_report

    evaluate, _ = oracle
    root = tmp_path / "exportable"
    workflow = prepare(diagnosis_config, root, Settings(api_key="unit-secret"), evaluator=evaluate)
    workflow.execute()
    exported = tmp_path / "published"
    result = export_workflow(root, exported)
    assert result["status"] == "completed"
    audited_files(exported)
    write_report(
        tmp_path / "html",
        {
            "title": "<script>bad()</script>",
            "summary": "<img src=x onerror=bad()>",
            "comparisons": [],
            "diagnoses": [],
        },
    )
    content = (tmp_path / "html/report.html").read_text(encoding="utf-8")
    assert "<script>" not in content and "<img src=x" not in content
