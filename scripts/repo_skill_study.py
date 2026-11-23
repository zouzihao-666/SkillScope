"""A frozen 12-condition, three-repeat skill comparison on one selected discovery task."""

import argparse
import collections
import json
import random
import shutil
import subprocess
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path

from scripts.continue_repo_study import final_grade_available
from scripts.repo_agent import MAX_OUTPUT, MAX_REQUESTS, run_agent
from scripts.repo_calibration import COLLECTION, ROOT, SCRIPTS, export, save
from scripts.repo_workspace import Workspace
from skillscope.batch import PRICE, estimate_cost, source_fingerprint
from skillscope.loader import digest, load_experiment
from skillscope.models import Condition, Skill
from skillscope.planner import conditions_for
from skillscope.report import wilson
from skillscope.sandbox import SandboxError, preflight
from skillscope.settings import load_settings

PLAN = COLLECTION / "skill-study-plan.json"
CALIBRATION = ROOT / "artifacts/controller-v4-20261123/report.json"
TASK = "dotenv-backslash"
WORKERS = 2


def make_plan(docker: str) -> dict:
    previous = json.loads(CALIBRATION.read_text(encoding="utf-8"))
    selected = previous["tasks"][TASK]
    if selected["hidden_graded"] != 2 or selected["passed"] != 1:
        raise ValueError("Selected discovery task no longer matches the disclosed calibration")
    experiment = load_experiment(ROOT / "benchmarks/stage3/experiment.json")
    conditions = conditions_for(experiment, controls=True)
    jobs = [
        {
            "id": f"{TASK}__{condition.id}__{repeat}",
            "task": TASK,
            "condition": condition.id,
            "repeat": repeat,
        }
        for repeat in (1, 2, 3)
        for condition in conditions
    ]
    random.Random(4201).shuffle(jobs)
    scripts = (*SCRIPTS, "repo_skills.py", "continue_repo_study.py", "repo_skill_study.py")
    return {
        "schema_version": 1,
        "purpose": "exploratory skill comparison on a task selected from disclosed discovery calibration",
        "controller": "observed_phase_boundaries_v4",
        "model": "deepseek-flash",
        "runs": jobs,
        "conditions": [c.model_dump(mode="json") for c in conditions],
        "skills": [s.model_dump(mode="json") for s in experiment.skills],
        "workspace_sha256": {TASK: Workspace(COLLECTION / TASK / "task.json").initial_fingerprint},
        "source_sha256": source_fingerprint(),
        "scripts_sha256": {
            name: digest((ROOT / "scripts" / name).read_text(encoding="utf-8")) for name in scripts
        },
        "image_id": preflight(docker),
        "order_seed": 4201,
        "selection_report_sha256": digest(CALIBRATION.read_text(encoding="utf-8")),
        "budget": {
            "max_runs": 36,
            "max_requests": 360,
            "per_run_requests": 10,
            "per_phase_requests": 4,
            "max_output_tokens": 2048,
            "workers": WORKERS,
            "max_estimated_usd": 3.0,
            "max_sdk_retries": 0,
        },
        "price_estimate": PRICE,
        "holdout": "No model calls or grading of dotenv-bom or any held-out task",
        "limitations": "One selected discovery issue, three repeats per condition. Character-matched neutral guide bodies do not match token counts or remove guide-name hints. Fresh histories per phase can retain indirect skill effects through summaries or patches. No population or causal claim; protocol failures separate from valid functional grades. Calibration not pooled with comparison.",
        "candidate_rule": "All required groups have three valid final grades; baseline=3/3, every single>=2/3, both neutral controls>=2/3, scoped>=2/3, and all or all-reversed<=1/3. Exploratory candidate only; no semantic-conflict proof.",
    }


def comparison_report(plan: dict, rows: list) -> dict:
    groups = {}
    for condition in plan["conditions"]:
        selected = [row["result"] for row in rows if row["job"]["condition"] == condition["id"]]
        groups[condition["id"]] = {
            "recorded": len(selected),
            "valid_final_grades": sum(final_grade_available(result) for result in selected),
            "passed": sum(
                final_grade_available(result) and result["status"] == "passed"
                for result in selected
            ),
            "functional_failures": sum(
                final_grade_available(result) and result["status"] == "failed"
                for result in selected
            ),
            "statuses": dict(collections.Counter(result["status"] for result in selected)),
            "calls": sum(result["calls_attempted"] for result in selected),
            "tokens": sum(result["reported_tokens"]["total_tokens"] for result in selected),
        }
        groups[condition["id"]]["descriptive_wilson95_valid"] = wilson(
            groups[condition["id"]]["passed"], groups[condition["id"]]["valid_final_grades"]
        )
    singles = [
        condition["id"] for condition in plan["conditions"] if condition["id"].startswith("single-")
    ]
    controls = ["baseline", *singles, "length-a", "length-b", "scoped"]
    common = all(groups[key]["valid_final_grades"] == 3 for key in controls)
    common = common and groups["baseline"]["passed"] == 3
    common = common and all(groups[key]["passed"] >= 2 for key in controls if key != "baseline")
    candidates = [
        key
        for key in ("all", "all-reversed")
        if common and groups[key]["valid_final_grades"] == 3 and groups[key]["passed"] <= 1
    ]
    return {
        "conditions": groups,
        "candidate_screen": {
            "candidates": candidates,
            "rule": plan["candidate_rule"],
            "interpretation": "Exploratory screen; missing or unsuccessful controls do not demonstrate an absence of effects.",
        },
    }


def run(output: Path):
    settings = load_settings()
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan != make_plan(settings.docker):
        raise ValueError("Frozen source, guides, inputs, image or schedule changed")
    committed = subprocess.run(
        ["git", "show", "HEAD:benchmarks/upstream/skill-study-plan.json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    if json.loads(committed) != plan:
        raise ValueError("Commit the study before any model calls")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    execute(plan, settings, output, commit, lambda: make_plan(settings.docker) == plan)


def execute(plan: dict, settings, output: Path, commit: str, unchanged):
    """Execute a committed schedule; caller supplies its exact source/input guard."""
    output.mkdir(parents=True, exist_ok=False)
    save(output / "manifest.json", {"preregistered_commit": commit, "plan": plan})
    shutil.copytree(COLLECTION / TASK, output / "inputs" / TASK)
    task_path = output / "inputs" / TASK / "task.json"
    if Workspace(task_path).initial_fingerprint != plan["workspace_sha256"][TASK]:
        raise ValueError("Frozen task snapshot changed")
    skills = tuple(Skill.model_validate(value) for value in plan["skills"])
    conditions = {value["id"]: Condition.model_validate(value) for value in plan["conditions"]}
    reservation = estimate_cost(
        {
            "prompt_tokens": MAX_REQUESTS * (65536 + 1024),
            "completion_tokens": MAX_REQUESTS * MAX_OUTPUT,
        }
    )
    completed, pending, scheduled = {}, {}, 0
    state = "running"

    def trial(job):
        directory = output / "runs" / job["id"]
        try:
            return run_agent(
                task_path,
                settings,
                directory,
                skills=skills,
                condition=conditions[job["condition"]],
            )
        except (SandboxError, OSError) as error:
            # A failed preflight happens before a run directory or any paid call.
            if directory.exists():
                raise
            directory.mkdir(parents=True)
            result = {
                "task": TASK,
                "condition": job["condition"],
                "status": "infrastructure_error",
                "error": type(error).__name__,
                "grading": None,
                "calls_attempted": 0,
                "responses_received": 0,
                "usage_complete": True,
                "reported_tokens": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "estimated_usd_upper": 0.0,
                "initial_workspace_sha256": plan["workspace_sha256"][TASK],
                "source_sha256": plan["source_sha256"],
                "runner_sha256": plan["scripts_sha256"]["repo_agent.py"],
            }
            save(directory / "workspace-final.json", Workspace(task_path).execution_snapshot())
            save(directory / "run.json", result)
            return result

    def record(job, result):
        completed[job["id"]] = {"job": job, "result": result}
        ordered = [completed[j["id"]] for j in plan["runs"] if j["id"] in completed]
        save(output / "results.json", ordered)
        print(
            f"{len(completed)}/{len(plan['runs'])} {job['id']}: {result['status']}; calls={result['calls_attempted']}",
            flush=True,
        )

    save(output / "results.json", [])
    executor = ThreadPoolExecutor(max_workers=WORKERS)
    try:
        while scheduled < len(plan["runs"]) or pending:
            while state == "running" and scheduled < len(plan["runs"]) and len(pending) < WORKERS:
                rows = list(completed.values())
                if any(not row["result"]["usage_complete"] for row in rows):
                    state = "unknown_usage_stopped"
                    break
                spent = sum(row["result"]["estimated_usd_upper"] for row in rows)
                calls = sum(row["result"]["calls_attempted"] for row in rows)
                if (
                    spent + (len(pending) + 1) * reservation > plan["budget"]["max_estimated_usd"]
                    or calls + (len(pending) + 1) * MAX_REQUESTS > plan["budget"]["max_requests"]
                ):
                    state = "budget_stopped"
                    break
                if not unchanged():
                    raise ValueError("Inputs changed during execution")
                job = plan["runs"][scheduled]
                pending[executor.submit(trial, job)] = job
                scheduled += 1
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                job = pending.pop(future)
                record(job, future.result())
        if len(completed) == len(plan["runs"]):
            state = "completed"
    finally:
        executor.shutdown(wait=True)
        for future, job in pending.items():
            if job["id"] not in completed:
                if (output / "runs" / job["id"] / "run.json").exists():
                    record(
                        job,
                        json.loads(
                            (output / "runs" / job["id"] / "run.json").read_text(encoding="utf-8")
                        ),
                    )
        save(
            output / "study.json",
            {
                "status": "interrupted" if state == "running" else state,
                "recorded": len(completed),
                "planned": len(plan["runs"]),
            },
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "run", "export"])
    parser.add_argument("--study", type=Path, default=Path("results/repo-skills-20261123"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/repo-skills-20261123"))
    arguments = parser.parse_args()
    if arguments.command == "plan":
        if PLAN.exists():
            raise ValueError("Existing study plan will not be overwritten")
        save(PLAN, make_plan(load_settings().docker))
    elif arguments.command == "run":
        run(arguments.study)
    else:
        manifest = json.loads((arguments.study / "manifest.json").read_text(encoding="utf-8"))
        rows = json.loads((arguments.study / "results.json").read_text(encoding="utf-8"))
        export(
            arguments.study,
            arguments.output,
            report_extra=comparison_report(manifest["plan"], rows),
        )


if __name__ == "__main__":
    main()
