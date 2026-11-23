import gzip
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "folder,calls,tokens",
    [("phase-finish-smoke-20261123", 8, 28235), ("phase-finish-smoke-v3-20261123", 6, 18915)],
)
def test_failed_engineering_versions_are_independent_and_checksum_complete(folder, calls, tokens):
    directory = ROOT / "artifacts" / folder
    for name, expected in json.loads((directory / "checksums.json").read_text()).items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected
    report = json.loads((directory / "report.json").read_text())
    (record,) = [
        json.loads(line)
        for line in gzip.decompress((directory / "raw-runs.jsonl.gz").read_bytes())
        .decode()
        .splitlines()
    ]
    assert report["calls"] == calls and report["reported_tokens"] == tokens
    assert record["result"]["status"] == "invalid_output"
    assert record["result"]["grading"] is None
    assert record["result"]["error"] == "Model ignored required phase-finish tool"
    assert record["job"]["task"] == "dotenv-comment"


def test_all_four_stopped_trials_are_preserved_and_not_reported_as_hidden_failures():
    directory = ROOT / "artifacts/repo-calibration-20261123"
    checksums = json.loads((directory / "checksums.json").read_text())
    for path, expected in checksums.items():
        assert hashlib.sha256((directory / path).read_bytes()).hexdigest() == expected
    manifest = json.loads((directory / "manifest.json").read_text())
    rows = json.loads((directory / "results.json").read_text())
    report = json.loads((directory / "report.json").read_text())
    records = [
        json.loads(line)
        for line in gzip.decompress((directory / "raw-runs.jsonl.gz").read_bytes())
        .decode()
        .splitlines()
    ]
    assert [row["job"] for row in rows] == manifest["plan"]["runs"]
    assert len(records) == len(rows) == 4
    assert report["calls"] == 24 and report["reported_tokens"] == 104585
    for row, record in zip(rows, records, strict=True):
        assert record["result"] == row["result"]
        result = row["result"]
        assert result["status"] == "budget_exhausted" and result["grading"] is None
        assert result["usage_complete"]
        responses = [e["response"] for e in record["trace"] if e["type"] == "response"]
        assert len(responses) == result["calls_attempted"]
        assert (
            sum(r["usage"]["total_tokens"] for r in responses)
            == result["reported_tokens"]["total_tokens"]
        )
        assert result["runner_sha256"] == manifest["plan"]["scripts_sha256"]["repo_agent.py"]
        assert row["job"]["task"] != "dotenv-bom"
