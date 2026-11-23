"""Freeze, run and export four baseline trials; never call the held-out task."""

import argparse
import gzip
import hashlib
import json
import random
import re
import shutil
import subprocess
from pathlib import Path

from dotenv import dotenv_values

from scripts.repo_agent import MAX_OUTPUT, MAX_REQUESTS, run_agent
from scripts.repo_workspace import Workspace
from skillscope.batch import PRICE, estimate_cost, source_fingerprint
from skillscope.loader import digest
from skillscope.sandbox import preflight
from skillscope.settings import load_settings

ROOT = Path(__file__).resolve().parents[1]
COLLECTION = ROOT / "benchmarks/upstream"
PLAN = COLLECTION / "calibration-plan.json"
SCRIPTS = (
    "repo_calibration.py",
    "repo_agent.py",
    "repo_tools.py",
    "repo_workspace.py",
    "repo_execution.py",
)


def save(path: Path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def make_plan(docker: str) -> dict:
    tasks = json.loads((COLLECTION / "collection.json").read_text())["tasks"]
    selected = [task["id"] for task in tasks if task["split"] == "discovery"]
    jobs = [
        {"id": f"{task}__{repeat}", "task": task, "repeat": repeat}
        for task in selected
        for repeat in (1, 2)
    ]
    random.Random(2718).shuffle(jobs)
    return {
        "schema_version": 1,
        "purpose": "difficulty calibration, not a skill comparison or generalization claim",
        "model": "deepseek-flash",
        "condition": "baseline",
        "seed": 2718,
        "runs": jobs,
        "workspace_sha256": {
            task: Workspace(COLLECTION / task / "task.json").initial_fingerprint
            for task in selected
        },
        "collection_sha256": digest((COLLECTION / "collection.json").read_text()),
        "source_sha256": source_fingerprint(),
        "scripts_sha256": {
            name: digest((ROOT / "scripts" / name).read_text(encoding="utf-8")) for name in SCRIPTS
        },
        "image_id": preflight(docker),
        "budget": {
            "max_runs": 4,
            "max_requests": 40,
            "per_run_requests": MAX_REQUESTS,
            "max_output_tokens": MAX_OUTPUT,
            "max_estimated_usd": 1.0,
            "max_sdk_retries": 0,
        },
        "price_estimate": PRICE,
        "holdout": "dotenv-bom: no model calls and no grading during calibration",
    }


def run(output: Path):
    settings = load_settings()
    plan = json.loads(PLAN.read_text())
    if plan != make_plan(settings.docker):
        raise ValueError("Frozen inputs, code or image changed; do not run this plan")
    registered = subprocess.run(
        ["git", "show", "HEAD:benchmarks/upstream/calibration-plan.json"],
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
    rows = []
    status = "running"
    # Independent immutable input copies; no reference is supplied to model tools.
    for task in plan["workspace_sha256"]:
        shutil.copytree(COLLECTION / task, output / "inputs" / task)
    reservation = estimate_cost(
        {
            "prompt_tokens": MAX_REQUESTS * (65536 + 1024),
            "completion_tokens": MAX_REQUESTS * MAX_OUTPUT,
        }
    )
    try:
        for job in plan["runs"]:
            spent = sum(row["result"]["estimated_usd_upper"] for row in rows)
            if spent + reservation > plan["budget"]["max_estimated_usd"]:
                status = "budget_stopped"
                break
            if any(not row["result"]["usage_complete"] for row in rows):
                status = "unknown_usage_stopped"
                break
            result = run_agent(
                output / "inputs" / job["task"] / "task.json", settings, output / "runs" / job["id"]
            )
            rows.append({"job": job, "result": result})
            save(output / "results.json", rows)
            print(
                f"{job['id']}: {result['status']}; calls={result['calls_attempted']}; tokens={result['reported_tokens']['total_tokens']}",
                flush=True,
            )
        else:
            status = "completed"
    finally:
        if status == "running":
            status = "interrupted"
        save(
            output / "study.json",
            {"status": status, "recorded": len(rows), "planned": len(plan["runs"])},
        )


def export(study: Path, output: Path):
    manifest = json.loads((study / "manifest.json").read_text())
    rows = json.loads((study / "results.json").read_text())
    state = json.loads((study / "study.json").read_text())
    plan = manifest["plan"]
    if state["status"] != "completed" or [row["job"] for row in rows] != plan["runs"]:
        raise ValueError("Expected every scheduled run in its original order")
    records = []
    for row in rows:
        directory = study / "runs" / row["job"]["id"]
        trace = [
            json.loads(line)
            for line in (directory / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        if (
            row["result"]["initial_workspace_sha256"]
            != plan["workspace_sha256"][row["job"]["task"]]
        ):
            raise ValueError("Task fingerprint changed")
        if (
            row["result"]["source_sha256"] != plan["source_sha256"]
            or row["result"]["runner_sha256"] != plan["scripts_sha256"]["repo_agent.py"]
        ):
            raise ValueError("Execution code differs from frozen plan")
        records.append(
            {
                **row,
                "trace": trace,
                "workspace": json.loads(
                    (directory / "workspace-final.json").read_text(encoding="utf-8")
                ),
                "grader_logs": {
                    str(path.relative_to(directory)).replace("\\", "/"): path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    for path in directory.rglob("grader.log")
                },
            }
        )
    raw = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
    ).encode()
    key = dotenv_values(ROOT / ".env").get("DEEPSEEK_API_KEY")
    if (key and key.encode() in raw) or re.search(
        rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})", raw
    ):
        raise ValueError("Credential-like content found; export aborted")
    report = {
        "purpose": plan["purpose"],
        "runs": len(rows),
        "calls": sum(row["result"]["calls_attempted"] for row in rows),
        "reported_tokens": sum(row["result"]["reported_tokens"]["total_tokens"] for row in rows),
        "usage_complete": all(row["result"]["usage_complete"] for row in rows),
        "estimated_usd_upper": sum(row["result"]["estimated_usd_upper"] for row in rows),
        "tasks": {
            task: {
                "recorded": sum(row["job"]["task"] == task for row in rows),
                "passed": sum(
                    row["job"]["task"] == task and row["result"]["status"] == "passed"
                    for row in rows
                ),
                "statuses": [row["result"]["status"] for row in rows if row["job"]["task"] == task],
            }
            for task in plan["workspace_sha256"]
        },
        "limitations": plan.get(
            "limitations",
            "Two related historical library issues, two repeats each. Author-written regression tests, no complete upstream suite. No holdout calls or grades. Descriptive only; no skill comparison.",
        ),
    }
    if (
        report["calls"] > plan["budget"]["max_requests"]
        or report["estimated_usd_upper"] > plan["budget"]["max_estimated_usd"]
    ):
        raise ValueError("Recorded use exceeds frozen budget")
    output.mkdir(parents=True, exist_ok=False)
    save(output / "manifest.json", manifest)
    save(output / "results.json", rows)
    save(output / "report.json", report)
    with (output / "raw-runs.jsonl.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as archive:
            archive.write(raw)
    save(
        output / "checksums.json",
        {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.iterdir())
            if p.is_file()
        },
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "run", "export"])
    parser.add_argument("--study", type=Path, default=Path("results/repo-calibration-20261123"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/repo-calibration-20261123"))
    arguments = parser.parse_args()
    if arguments.command == "plan":
        if PLAN.exists():
            raise ValueError("Existing frozen plan will not be overwritten")
        save(PLAN, make_plan(load_settings().docker))
    elif arguments.command == "run":
        run(arguments.study)
    else:
        export(arguments.study, arguments.output)


if __name__ == "__main__":
    main()
