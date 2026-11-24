import gzip
import hashlib
import json
from pathlib import Path

import pytest

from skillscope.evidence import audited_files
from skillscope.policy import load_saved_policy

ROOT = Path(__file__).resolve().parents[1]


def test_published_workflow_preserves_frozen_bytes_and_real_validation():
    root = ROOT / "artifacts/v06-complete-diagnosis"
    audited_files(root)
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    assert state["status"] == "completed" and len(state["trials"]) == 21
    assert len({value["id"] for value in state["trials"]}) == 21
    assert state["budget"]["logged_call_attempts"] == 197
    assert state["budget"]["usage_complete"] and state["budget"]["unknown_reserved_usd"] == 0
    assert hashlib.sha256((root / "plan.json").read_bytes()).hexdigest() == state["plan_sha256"]
    assert (
        hashlib.sha256((root / "policy.json").read_bytes()).hexdigest()
        == state["policy_frozen_sha256"]
    )
    validation = json.loads((root / "policy-validation.json").read_text(encoding="utf-8"))
    assert validation["policy_sha256"] == state["policy_frozen_sha256"]
    assert len(validation["task_results"]) == 3
    assert all(
        value["measurement"]["passed"] == 3 and value["measurement"]["unresolved"] == 0
        for value in validation["task_results"]
    )
    diagnosis = state["diagnoses"]["dotenv-backslash"]
    assert diagnosis["classification"] == "baseline_unreliable" and not diagnosis["suspects"]
    assert (
        diagnosis["all"]["passed"] == 2
        and diagnosis["selected_policy"]["measurement"]["passed"] == 3
    )
    assert all(
        trial["split"] == "discovery"
        for trial in state["trials"]
        if trial["id"] in diagnosis["selected_policy"]["measurement"]["run_ids"]
    )
    load_saved_policy(root)
    raw = json.loads(gzip.decompress((root / "raw-workflow.json.gz").read_bytes()))
    assert len(raw["records"]) == 21
    assert (
        sum(event["type"] == "request" for record in raw["records"] for event in record["trace"])
        == 197
    )


def test_direct_application_is_separate_and_aggregate_cost_stays_bounded():
    root = ROOT / "artifacts/v06-policy-application"
    audited_files(root)
    result = json.loads((root / "run.json").read_text(encoding="utf-8"))
    assert result["status"] == "passed" and result["grading"]["tests"] == 9
    assert result["calls_attempted"] == 8 and result["usage_complete"]
    applied = json.loads((root / "applied-policy.json").read_text(encoding="utf-8"))
    policy = ROOT / "artifacts/v06-complete-diagnosis/policy.json"
    assert applied["source_policy_sha256"] == hashlib.sha256(policy.read_bytes()).hexdigest()
    assert applied["current_task"] == "dotenv-comment"
    assert (root / "changes.patch").read_text(encoding="utf-8").startswith("--- a/dotenv/parser.py")
    first = json.loads(
        (ROOT / "artifacts/v06-initial-acceptance/state.json").read_text(encoding="utf-8")
    )["budget"]
    second = json.loads(
        (ROOT / "artifacts/v06-complete-diagnosis/state.json").read_text(encoding="utf-8")
    )["budget"]
    assert (
        first["logged_call_attempts"] + second["logged_call_attempts"] + result["calls_attempted"]
        == 265
    )
    cost = (
        first["known_response_estimate_usd"]
        + second["known_response_estimate_usd"]
        + result["estimated_usd_upper"]
    )
    assert cost == pytest.approx(0.396879804) and cost < 1.5
