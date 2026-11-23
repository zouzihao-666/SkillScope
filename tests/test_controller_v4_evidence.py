import gzip
import hashlib
import json
from pathlib import Path


def test_real_controller_validation_and_fresh_calibration_are_separate():
    directory = Path(__file__).resolve().parents[1] / "artifacts/controller-v4-20261123"
    for name, expected in json.loads((directory / "checksums.json").read_text()).items():
        assert hashlib.sha256((directory / name).read_bytes()).hexdigest() == expected
    report = json.loads((directory / "report.json").read_text())
    records = [
        json.loads(line)
        for line in gzip.decompress((directory / "raw-runs.jsonl.gz").read_bytes())
        .decode()
        .splitlines()
    ]
    assert report["calls"] == 50 and report["reported_tokens"] == 204116
    assert report["cohorts"]["engineering"]["recorded"] == 1
    assert report["cohorts"]["calibration"]["recorded"] == 4
    assert sum(task["passed"] for task in report["tasks"].values()) == 3
    assert sum(task["recorded"] for task in report["tasks"].values()) == 4
    for record in records:
        result = record["result"]
        assert result["grading"]["status"] in ("passed", "failed")
        assert result["controller"] == "observed_phase_boundaries_v4"
        assert result["calls_attempted"] == 10 and result["usage_complete"]
        assert {
            event["stage"]
            for event in record["trace"]
            if event["type"] in ("phase_finished", "phase_budget_transition")
        } == {"investigate", "implement", "verify"}
