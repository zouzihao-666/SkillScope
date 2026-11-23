import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "artifacts/budget-study-20261123"


def records():
    with gzip.open(ROOT / "raw-runs.jsonl.gz", "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def test_budget_evidence_checksums_and_balanced_matrix():
    hashes = json.loads((ROOT / "checksums.json").read_text(encoding="utf-8"))
    for name, expected in hashes.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    rows = records()
    assert len(rows) == len({row["run"]["job"]["id"] for row in rows}) == 40
    groups = Counter((row["run"]["job"]["condition_id"], row["run"]["job"]["cap"]) for row in rows)
    assert len(groups) == 8 and set(groups.values()) == {5}


def test_caps_usage_and_truncations_match_actual_api_responses():
    rows = records()
    responses = [
        event["response"] for row in rows for event in row["trace"] if event["type"] == "response"
    ]
    assert len(responses) == 114
    assert sum(response["usage"]["total_tokens"] for response in responses) == 167289
    failed = [row for row in rows if row["run"]["status"] != "passed"]
    assert len(failed) == 3
    assert all(
        row["run"]["job"]["cap"] == 1024 and row["run"]["length_truncation"] for row in failed
    )
    for row in rows:
        assert row["run"]["usage_complete"]
        for event in row["trace"]:
            if event["type"] == "request":
                assert event["max_tokens"] == row["run"]["job"]["cap"]


def test_candidates_are_original_model_submissions_and_report_preserves_failures():
    rows = records()
    for row in rows:
        if row["candidate"] is None:
            assert row["run"]["length_truncation"]
            continue
        assert (
            hashlib.sha256(row["candidate"].encode("utf-8")).hexdigest() == row["candidate_sha256"]
        )
        response = next(
            event["response"]
            for event in row["trace"]
            if event["type"] == "response" and event["stage"] == "implement"
        )
        call = response["choices"][0]["message"]["tool_calls"][0]
        assert (
            json.loads(call["function"]["arguments"])["code"].replace("\r\n", "\n")
            == row["candidate"]
        )
    report = json.loads((ROOT / "report.json").read_text(encoding="utf-8"))
    assert report["groups"]["all-reversed/1024"]["passed"] == 3
    assert report["groups"]["all-reversed/2048"]["passed"] == 5
    assert report["observed_budget_sensitive_candidates"] == ["all-reversed"]
