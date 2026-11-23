"""Validate controller v4, then execute four independent, fixed baseline trials."""

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from scripts.repo_agent import MAX_OUTPUT, MAX_REQUESTS, run_agent
from scripts.repo_calibration import COLLECTION, ROOT, export, save
from scripts.repo_calibration import make_plan as baseline_plan
from scripts.repo_workspace import Workspace
from skillscope.batch import estimate_cost
from skillscope.loader import digest
from skillscope.settings import load_settings

PLAN = COLLECTION / "controller-v4-plan.json"


def make_plan(docker: str) -> dict:
    plan = baseline_plan(docker)
    pilot = {"id": "v4-engineering", "task": "dotenv-comment", "repeat": 1, "cohort": "engineering"}
    plan["runs"] = [pilot] + [{**job, "cohort": "calibration"} for job in plan["runs"]]
    plan["purpose"] = (
        "controller-v4 engineering gate followed by four independent baseline calibration trials"
    )
    plan["controller"] = "observed_phase_boundaries_v4"
    plan["budget"].update(max_runs=5, max_requests=50, max_estimated_usd=1.5, per_phase_requests=4)
    plan["scripts_sha256"]["continue_repo_study.py"] = digest(
        Path(__file__).read_text(encoding="utf-8")
    )
    plan["limitations"] = (
        "Engineering pilot excluded from per-task calibration results. Two related library issues, two fresh repeats each. Old protocols and results remain separate. No holdout calls or grades. Author-written regression tests, no complete upstream suite; descriptive only."
    )
    plan["gate"] = (
        "Pilot must complete all three phases and receive a valid passed/failed final hidden grade. Patch success is not a gate. Unknown usage stops further calls."
    )
    return plan


def final_grade_available(result: dict) -> bool:
    grade = result.get("grading")
    return (
        isinstance(grade, dict)
        and grade.get("status") in ("passed", "failed")
        and isinstance(grade.get("tests"), int)
        and grade["tests"] > 0
        and result.get("status") == grade["status"]
    )


def can_start(plan: dict, rows: list) -> str | None:
    if any(not row["result"]["usage_complete"] for row in rows):
        return "unknown_usage_stopped"
    if rows and not final_grade_available(rows[0]["result"]):
        return "pilot_gate_stopped"
    reservation = estimate_cost(
        {
            "prompt_tokens": MAX_REQUESTS * (65536 + 1024),
            "completion_tokens": MAX_REQUESTS * MAX_OUTPUT,
        }
    )
    if (
        sum(row["result"]["calls_attempted"] for row in rows) + MAX_REQUESTS
        > plan["budget"]["max_requests"]
        or sum(row["result"]["estimated_usd_upper"] for row in rows) + reservation
        > plan["budget"]["max_estimated_usd"]
    ):
        return "budget_stopped"
    return None


def run(output: Path):
    settings = load_settings()
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan != make_plan(settings.docker):
        raise ValueError("Code, inputs, image or schedule differ from frozen plan")
    registered = subprocess.run(
        ["git", "show", "HEAD:benchmarks/upstream/controller-v4-plan.json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    if json.loads(registered) != plan:
        raise ValueError("Plan must be committed before paid calls")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    output.mkdir(parents=True, exist_ok=False)
    save(output / "manifest.json", {"preregistered_commit": commit, "plan": plan})
    for task, fingerprint in plan["workspace_sha256"].items():
        shutil.copytree(COLLECTION / task, output / "inputs" / task)
        if Workspace(output / "inputs" / task / "task.json").initial_fingerprint != fingerprint:
            raise ValueError("Input snapshot does not match plan")
    rows, state = [], "running"
    save(output / "results.json", rows)
    try:
        for job in plan["runs"]:
            reason = can_start(plan, rows)
            if reason:
                state = reason
                break
            if make_plan(settings.docker) != plan:
                raise ValueError("Execution inputs changed after freeze")
            directory = output / "runs" / job["id"]
            try:
                result = run_agent(
                    output / "inputs" / job["task"] / "task.json", settings, directory
                )
            except BaseException:
                if (directory / "run.json").exists():
                    rows.append(
                        {
                            "job": job,
                            "result": json.loads(
                                (directory / "run.json").read_text(encoding="utf-8")
                            ),
                        }
                    )
                    save(output / "results.json", rows)
                raise
            rows.append({"job": job, "result": result})
            save(output / "results.json", rows)
            print(
                f"{job['id']}: {result['status']}; hidden={result.get('grading')}; calls={result['calls_attempted']}",
                flush=True,
            )
        else:
            state = "completed"
    finally:
        save(
            output / "study.json",
            {
                "status": "interrupted" if state == "running" else state,
                "recorded": len(rows),
                "planned": len(plan["runs"]),
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "run", "export"])
    parser.add_argument("--study", type=Path, default=Path("results/controller-v4-20261123"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/controller-v4-20261123"))
    arguments = parser.parse_args()
    if arguments.command == "plan":
        if PLAN.exists():
            raise ValueError("Frozen plan will not be overwritten")
        save(PLAN, make_plan(load_settings().docker))
    elif arguments.command == "run":
        run(arguments.study)
    else:
        export(arguments.study, arguments.output)


if __name__ == "__main__":
    main()
