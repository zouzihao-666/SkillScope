import gzip
import hashlib
import json

import pytest

from scripts import continue_skill_study as study


def test_continuation_excludes_unknown_trials_and_reserves_their_entire_budget(monkeypatch):
    original = json.loads((study.PARENT / "manifest.json").read_text())["plan"]
    monkeypatch.setattr(study, "preflight", lambda _: original["image_id"])
    plan = study.make_plan("unused")
    assert plan["runs"] == original["runs"][2:]
    assert len(plan["runs"]) == 34
    assert not {row["id"] for row in original["runs"][:2]} & {row["id"] for row in plan["runs"]}
    assert plan["skills"] == original["skills"] and plan["conditions"] == original["conditions"]
    assert plan["candidate_rule"] == original["candidate_rule"]
    assert plan["budget"]["max_requests"] == 340
    assert plan["unknown_usage_reserved_usd_upper"] == pytest.approx(0.448512)
    assert plan["budget"]["max_estimated_usd"] + plan[
        "unknown_usage_reserved_usd_upper"
    ] == pytest.approx(3.0)
    for name in study.RUNTIME:
        assert plan["scripts_sha256"][name] == original["scripts_sha256"][name]


def test_interrupted_evidence_contains_requests_without_invented_responses_or_grades():
    for name, expected in json.loads((study.PARENT / "checksums.json").read_text()).items():
        assert hashlib.sha256((study.PARENT / name).read_bytes()).hexdigest() == expected
    records = [
        json.loads(line)
        for line in gzip.decompress((study.PARENT / "raw-runs.jsonl.gz").read_bytes())
        .decode()
        .splitlines()
    ]
    assert len(records) == 2
    for record in records:
        assert record["result"]["status"] == "interrupted"
        assert record["result"]["usage_complete"] is False
        assert record["result"]["grading"] is None
        assert [event["type"] for event in record["trace"]] == ["request"]
