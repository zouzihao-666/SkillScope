import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from skillscope.loader import load_experiment
from skillscope.report import build_report

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts/stage3-20261123"


@pytest.fixture(scope="module")
def records():
    with gzip.open(EVIDENCE / "raw-runs.jsonl.gz", "rt", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream]


def test_published_checksums_and_corpus_match_frozen_experiment():
    hashes = json.loads((EVIDENCE / "checksums.json").read_text(encoding="utf-8"))
    for filename, expected in hashes.items():
        assert hashlib.sha256((EVIDENCE / filename).read_bytes()).hexdigest() == expected
    manifest = json.loads((EVIDENCE / "manifest.json").read_text(encoding="utf-8"))
    assert (
        load_experiment(ROOT / "benchmarks/stage3/experiment.json").sha256
        == manifest["experiment_sha256"]
    )
    check = json.loads((EVIDENCE / "corpus-check.json").read_text(encoding="utf-8"))
    assert check["passed"] and check["experiment_sha256"] == manifest["experiment_sha256"]


def test_archive_has_balanced_complete_main_runs_and_separate_pilot(records):
    assert len(records) == 148
    assert len({record["run"]["job"]["id"] for record in records}) == 148
    main = [record for record in records if record["run"]["job"]["phase"] == "main"]
    pilot = [record for record in records if record["run"]["job"]["phase"] == "pilot"]
    assert len(main) == 144 and len(pilot) == 4
    assert all(record["run"]["status"] == "passed" for record in pilot)
    pairs = Counter(
        (record["run"]["job"]["task_id"], record["run"]["job"]["condition_id"]) for record in main
    )
    assert len(pairs) == 48 and set(pairs.values()) == {3}
    assert not any(
        record["run"]["job"]["task_id"] in ("deduplicate", "parse-duration") for record in records
    )


def test_usage_matches_every_actual_response_and_is_within_budget(records):
    responses = [
        event["response"]
        for record in records
        for event in record["trace"]
        if event["type"] == "response"
    ]
    requests = [
        event for record in records for event in record["trace"] if event["type"] == "request"
    ]
    assert len(responses) == len(requests) == 442
    assert sum(response["usage"]["total_tokens"] for response in responses) == 510231
    assert sum(record["run"]["reported_tokens"]["total_tokens"] for record in records) == 510231
    assert all(record["run"]["usage_complete"] for record in records)
    status = json.loads((EVIDENCE / "batch.json").read_text(encoding="utf-8"))
    limits = json.loads((EVIDENCE / "manifest.json").read_text(encoding="utf-8"))["limits"]
    assert status["calls_attempted"] <= limits["max_calls"]
    assert status["reported_tokens"] <= limits["max_reported_tokens"]
    assert status["estimated_usd_upper"] <= limits["max_estimated_usd"]


def test_each_candidate_is_the_actual_model_submission(records):
    for record in records:
        code = record["candidate"]
        if code is None:
            assert record["run"]["status"] == "invalid_output"
            continue
        assert hashlib.sha256(code.encode("utf-8")).hexdigest() == record["candidate_sha256"]
        submitted = [
            event
            for event in record["trace"]
            if event["type"] == "response" and event["stage"] == "implement"
        ]
        assert len(submitted) == 1
        call = submitted[0]["response"]["choices"][0]["message"]["tool_calls"][0]
        assert json.loads(call["function"]["arguments"])["code"].replace("\r\n", "\n") == code


def test_single_failure_is_retained_as_a_length_truncation(records):
    failed = [record for record in records if record["run"]["status"] != "passed"]
    assert len(failed) == 1
    record = failed[0]
    assert record["run"]["job"]["id"] == "get-path__all-reversed__001"
    assert record["run"]["grading"] is None and record["candidate"] is None
    responses = [event for event in record["trace"] if event["type"] == "response"]
    assert len(responses) == 1 and responses[0]["stage"] == "investigate"
    assert responses[0]["response"]["choices"][0]["finish_reason"] == "length"
    assert responses[0]["response"]["usage"]["completion_tokens"] == 1024


def test_report_recomputes_from_published_records_without_an_api():
    actual = build_report(EVIDENCE)
    stored = json.loads((EVIDENCE / "report.json").read_text(encoding="utf-8"))
    assert actual["main_runs_recorded"] == 144
    assert actual["groups"]["baseline"]["successes"] == 12
    assert actual["groups"]["all"]["successes"] == 12
    assert actual["groups"]["all-reversed"]["successes"] == 11
    assert not actual["candidate_combinations"]
    assert actual["missing_outcomes"] == 0
    for name in actual["groups"]:
        assert actual["groups"][name]["successes"] == stored["groups"][name]["successes"]
        assert actual["groups"][name]["estimated_usd_upper"] == pytest.approx(
            stored["groups"][name]["estimated_usd_upper"]
        )
