import gzip
import hashlib
import json
from pathlib import Path
from shutil import copytree

import pytest

from scripts.diagnosis_readiness import inspect

EVIDENCE = Path(__file__).resolve().parents[1] / "artifacts/repo-skills-20261123"


def test_every_scheduled_condition_keeps_its_functional_protocol_and_unknown_outcomes():
    manifest = json.loads((EVIDENCE / "manifest.json").read_text())
    report = json.loads((EVIDENCE / "report.json").read_text())
    rows = json.loads((EVIDENCE / "results.json").read_text())
    records = [
        json.loads(line)
        for line in gzip.decompress((EVIDENCE / "raw-runs.jsonl.gz").read_bytes())
        .decode()
        .splitlines()
    ]
    assert len(rows) == len(records) == 36
    assert [row["job"] for row in rows] == manifest["plan"]["runs"]
    assert report["calls"] == 335 and report["reported_tokens"] == 1780520
    assert sum(row["result"]["status"] == "passed" for row in rows) == 20
    assert sum(row["result"]["status"] == "failed" for row in rows) == 13
    assert sum(row["result"]["status"] == "invalid_output" for row in rows) == 1
    assert sum(row["result"]["status"] == "interrupted" for row in rows) == 2
    assert not report["usage_complete"]
    assert report["unknown_usage_reserved_usd_upper"] == pytest.approx(0.448512)
    assert report["conservative_cost_bound_usd"] == pytest.approx(0.890258928)
    assert report["candidate_screen"]["candidates"] == []
    for row, record in zip(rows, records, strict=True):
        assert row["job"] == record["job"] and row["result"] == record["result"]
        assert row["result"]["runner_sha256"] == manifest["plan"]["scripts_sha256"]["repo_agent.py"]
        assert (
            sum(event["type"] == "request" for event in record["trace"])
            == row["result"]["calls_attempted"]
        )


def test_readiness_refuses_missing_controls_and_detects_tampered_evidence(tmp_path):
    gate = inspect(EVIDENCE)
    assert gate["status"] == "insufficient_evidence"
    assert gate["groups_without_three_valid_grades"] == ["baseline", "single-root-cause", "scoped"]
    assert gate["single_skill_low_success"] == ["single-edge-cases", "single-input-validation"]
    assert gate["scheduled_paid_runs"] == 0 and not gate["holdout_opened"]
    copied = tmp_path / "evidence"
    copytree(EVIDENCE, copied)
    (copied / "report.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum mismatch"):
        inspect(copied)
    expected = json.loads((EVIDENCE / "checksums.json").read_text())
    assert (
        hashlib.sha256((EVIDENCE / "report.json").read_bytes()).hexdigest()
        == expected["report.json"]
    )
