import gzip
import hashlib
import json
from pathlib import Path

from scripts.repo_workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts/repo-prototype-20261123"


def records():
    with gzip.open(EVIDENCE / "raw-attempts.jsonl.gz", "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def test_all_engineering_attempts_and_their_usage_are_retained():
    rows = records()
    assert [row["version"] for row in rows] == ["v1", "v2", "v3"]
    assert [row["run"]["status"] for row in rows] == ["invalid_output", "invalid_output", "passed"]
    responses = [
        event["response"] for row in rows for event in row["trace"] if event["type"] == "response"
    ]
    assert len(responses) == 14
    assert sum(response["usage"]["total_tokens"] for response in responses) == 25225
    total = json.loads((EVIDENCE / "totals.json").read_text(encoding="utf-8"))
    assert total["calls"] == 14 and total["reported_tokens"] == 25225
    assert total["estimated_usd_upper"] <= total["max_estimated_usd"]


def test_checksum_and_workspace_fingerprints_match_original_task():
    hashes = json.loads((EVIDENCE / "checksums.json").read_text(encoding="utf-8"))
    for name, expected in hashes.items():
        assert hashlib.sha256((EVIDENCE / name).read_bytes()).hexdigest() == expected
    for row in records():
        workspace = Workspace(ROOT / "benchmarks/repo-prototype/cart/task.json")
        assert workspace.initial_fingerprint == row["run"]["initial_workspace_sha256"]
        workspace.write_files({path: row["workspace"][path] for path in workspace.editable})
        assert workspace.fingerprint() == row["run"]["final_workspace_sha256"]


def test_visible_tool_trace_has_no_hidden_grader_and_respects_stage_permissions():
    hidden = (ROOT / "benchmarks/repo-prototype/cart/hidden_tests.py").read_text(encoding="utf-8")
    rows = records()
    for row in rows:
        assert hidden not in json.dumps(row["trace"], ensure_ascii=False)
        assert row["run"]["calls_attempted"] <= 10
        assert row["run"]["public_test_runs_by_model"] <= 2
        for event in row["trace"]:
            if (
                event["type"] == "tool_result"
                and event["name"] in ("write_file", "write_files")
                and event["result"]["ok"]
            ):
                assert event["stage"] == "implement"
    final = rows[-1]
    assert final["run"]["initial_public"]["status"] == "failed"
    assert final["run"]["grading"]["status"] == "passed"
    assert final["run"]["grading"]["tests"] == 19
    assert final["run"]["public_test_runs_by_model"] == 2
