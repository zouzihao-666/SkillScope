"""Audit a comparison artifact and report whether combination diagnosis has evidence."""

import argparse
import hashlib
import json
from pathlib import Path

from scripts.repo_calibration import save
from scripts.repo_skill_study import comparison_report


def inspect(directory: Path) -> dict:
    checksums = json.loads((directory / "checksums.json").read_text(encoding="utf-8"))
    for name, expected in checksums.items():
        if Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("Checksum inventory must contain plain file names")
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Evidence checksum mismatch: {name}")
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    rows = json.loads((directory / "results.json").read_text(encoding="utf-8"))
    recalculated = comparison_report(manifest["plan"], rows)
    if (
        recalculated["conditions"] != report["conditions"]
        or recalculated["candidate_screen"] != report["candidate_screen"]
    ):
        raise ValueError("Reported comparison does not match the recorded results")
    groups = recalculated["conditions"]
    candidates = recalculated["candidate_screen"]["candidates"]
    return {
        "status": "candidate_needs_confirmation" if candidates else "insufficient_evidence",
        "evidence_report_sha256": hashlib.sha256(
            (directory / "report.json").read_bytes()
        ).hexdigest(),
        "candidates": candidates,
        "groups_without_three_valid_grades": [
            key for key, value in groups.items() if value["valid_final_grades"] != 3
        ],
        "single_skill_low_success": [
            key
            for key, value in groups.items()
            if key.startswith("single-")
            and value["valid_final_grades"] == 3
            and value["passed"] <= 1
        ],
        "scheduled_paid_runs": 0,
        "automatic_policy_validated": False,
        "holdout_opened": False,
        "next_step": "Preregister independent confirmation and budget/format controls; do not infer a combination interaction from low-performing individual skills or missing grades.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.output.exists():
        raise ValueError("Existing readiness records are not overwritten")
    result = inspect(arguments.evidence)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    save(arguments.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
