"""One separately registered engineering check, within the original total spending cap."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from scripts.repo_agent import MAX_OUTPUT, MAX_REQUESTS, run_agent
from scripts.repo_calibration import COLLECTION, ROOT, export, make_plan, save
from skillscope.batch import estimate_cost
from skillscope.loader import digest
from skillscope.settings import load_settings

PLAN = COLLECTION / "phase-finish-smoke-plan.json"
PREVIOUS = ROOT / "artifacts/repo-calibration-20261123/report.json"


def plan(docker):
    value = make_plan(docker)
    value["runs"] = [{"id": "dotenv-comment__controller-v2", "task": "dotenv-comment", "repeat": 1}]
    value["workspace_sha256"] = {"dotenv-comment": value["workspace_sha256"]["dotenv-comment"]}
    value["scripts_sha256"]["phase_finish_smoke.py"] = digest(
        Path(__file__).read_text(encoding="utf-8")
    )
    value["purpose"] = (
        "one engineering check of reserved phase completion; not a replacement calibration sample"
    )
    value["limitations"] = (
        "Selected to check the phase controller after four budget failures; different protocol, no pooled success rate. No holdout calls or grades. Not difficulty calibration or a skill experiment."
    )
    value["budget"].update(max_runs=1, max_requests=10)
    value["previous_report_sha256"] = digest(PREVIOUS.read_text(encoding="utf-8"))
    return value


def run(output):
    settings = load_settings()
    frozen = json.loads(PLAN.read_text(encoding="utf-8"))
    if frozen != plan(settings.docker):
        raise ValueError("Code, input or image differs from engineering plan")
    registered = subprocess.run(
        ["git", "show", "HEAD:benchmarks/upstream/phase-finish-smoke-plan.json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    if json.loads(registered) != frozen:
        raise ValueError("Engineering plan must be committed first")
    previous = json.loads(PREVIOUS.read_text(encoding="utf-8"))
    reservation = estimate_cost(
        {
            "prompt_tokens": MAX_REQUESTS * (65536 + 1024),
            "completion_tokens": MAX_REQUESTS * MAX_OUTPUT,
        }
    )
    if (
        not previous["usage_complete"]
        or previous["calls"] + MAX_REQUESTS > 40
        or previous["estimated_usd_upper"] + reservation > 1.0
    ):
        raise ValueError("Original combined request/spending cap cannot reserve this check")
    output.mkdir(parents=True, exist_ok=False)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    save(output / "manifest.json", {"preregistered_commit": commit, "plan": frozen})
    job = frozen["runs"][0]
    shutil.copytree(COLLECTION / job["task"], output / "inputs" / job["task"])
    result = run_agent(
        output / "inputs" / job["task"] / "task.json", settings, output / "runs" / job["id"]
    )
    save(output / "results.json", [{"job": job, "result": result}])
    save(output / "study.json", {"status": "completed", "recorded": 1, "planned": 1})
    print(
        json.dumps(
            {
                key: result.get(key)
                for key in (
                    "status",
                    "error",
                    "grading",
                    "calls_attempted",
                    "reported_tokens",
                    "estimated_usd_upper",
                )
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "run", "export"])
    parser.add_argument("--study", type=Path, default=Path("results/phase-finish-smoke-20261123"))
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/phase-finish-smoke-20261123")
    )
    arguments = parser.parse_args()
    if arguments.command == "plan":
        if PLAN.exists():
            raise ValueError("Frozen engineering plan will not be overwritten")
        save(PLAN, plan(load_settings().docker))
    elif arguments.command == "run":
        run(arguments.study)
    else:
        export(arguments.study, arguments.output)


if __name__ == "__main__":
    main()
