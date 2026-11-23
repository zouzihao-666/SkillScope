"""Continue only previously unattempted trials, reserving unknown interrupted usage."""

import argparse
import copy
import json
import shutil
import subprocess
from pathlib import Path

from scripts.repo_calibration import COLLECTION, ROOT, export, save
from scripts.repo_skill_study import comparison_report, execute
from skillscope.batch import source_fingerprint
from skillscope.loader import digest
from skillscope.sandbox import preflight
from skillscope.settings import load_settings

PARENT = ROOT / "artifacts/repo-skills-interrupted-20261123"
PLAN = COLLECTION / "skill-continuation-plan.json"
RUNTIME = (
    "repo_agent.py",
    "repo_tools.py",
    "repo_workspace.py",
    "repo_execution.py",
    "repo_skills.py",
)


def make_plan(docker):
    manifest = json.loads((PARENT / "manifest.json").read_text(encoding="utf-8"))
    prior = json.loads((PARENT / "results.json").read_text(encoding="utf-8"))
    original = manifest["plan"]
    if not prior or [row["job"] for row in prior] != original["runs"][: len(prior)]:
        raise ValueError("Interrupted records are not the original schedule prefix")
    if any(
        row["result"]["status"] != "interrupted" or row["result"]["usage_complete"] for row in prior
    ):
        raise ValueError("This continuation is only for the documented interrupted prefix")
    reserved = sum(row["result"].get("unknown_usage_reserved_usd_upper", 0) for row in prior)
    if reserved <= 0:
        raise ValueError("Unknown calls require a full conservative reservation")
    for name in RUNTIME:
        if (
            digest((ROOT / "scripts" / name).read_text(encoding="utf-8"))
            != original["scripts_sha256"][name]
        ):
            raise ValueError("Model execution code changed; this continuation must preserve it")
    if (
        source_fingerprint() != original["source_sha256"]
        or preflight(docker) != original["image_id"]
    ):
        raise ValueError("Core execution source or image changed")
    plan = copy.deepcopy(original)
    plan["runs"] = original["runs"][len(prior) :]
    plan["purpose"] = (
        "Continue only unattempted scheduled trials after a documented process/daemon interruption; interrupted trials remain unknown and are never retried"
    )
    plan["parent_checksums_sha256"] = digest(
        (PARENT / "checksums.json").read_text(encoding="utf-8")
    )
    plan["unknown_usage_reserved_usd_upper"] = reserved
    plan["budget"]["max_runs"] = len(plan["runs"])
    plan["budget"]["max_requests"] -= len(prior) * original["budget"]["per_run_requests"]
    plan["budget"]["max_estimated_usd"] -= reserved
    for name in ("repo_calibration.py", "repo_skill_study.py", "continue_skill_study.py"):
        plan["scripts_sha256"][name] = digest((ROOT / "scripts" / name).read_text(encoding="utf-8"))
    return plan


def run(output):
    settings = load_settings()
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    if plan != make_plan(settings.docker):
        raise ValueError("Continuation inputs differ from committed reservation and schedule")
    committed = subprocess.run(
        ["git", "show", "HEAD:benchmarks/upstream/skill-continuation-plan.json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout
    if json.loads(committed) != plan:
        raise ValueError("Commit the continuation before new calls")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    execute(plan, settings, output, commit, lambda: make_plan(settings.docker) == plan)


def combine(study: Path, output: Path):
    original = ROOT / "results/repo-skills-20261123"
    combined = ROOT / "results/repo-skills-combined-20261123"
    parent_manifest = json.loads((PARENT / "manifest.json").read_text(encoding="utf-8"))
    continuation = json.loads((study / "manifest.json").read_text(encoding="utf-8"))
    old = json.loads((PARENT / "results.json").read_text(encoding="utf-8"))
    new = json.loads((study / "results.json").read_text(encoding="utf-8"))
    rows = [{**row, "execution_segment": "interrupted_initial"} for row in old] + [
        {**row, "execution_segment": "continuation"} for row in new
    ]
    plan = parent_manifest["plan"]
    if [row["job"] for row in rows] != plan["runs"][: len(rows)]:
        raise ValueError("Continuation changed or retried an original schedule entry")
    combined.mkdir(parents=True, exist_ok=False)
    for directory, selected in ((original, old), (study, new)):
        for row in selected:
            shutil.copytree(
                directory / "runs" / row["job"]["id"], combined / "runs" / row["job"]["id"]
            )
    save(
        combined / "manifest.json",
        {
            **parent_manifest,
            "continuation": continuation,
            "interruption_note": "Two original trials retained as interrupted/unknown. Only previously unattempted trials continued with unchanged model runner, guides, task, image and candidate rule. Unknown trials reserved their full original per-run ceiling.",
        },
    )
    save(combined / "results.json", rows)
    state = json.loads((study / "study.json").read_text(encoding="utf-8"))
    save(
        combined / "study.json",
        {
            "status": "completed" if len(rows) == len(plan["runs"]) else state["status"],
            "recorded": len(rows),
            "planned": len(plan["runs"]),
        },
    )
    report = comparison_report(plan, rows)
    report["execution_note"] = (
        "All interrupted trials remain in denominators and uncertainty records; continuation does not replace them. No claim of complete billing."
    )
    export(combined, output, report_extra=report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["plan", "run", "export", "combine"])
    parser.add_argument(
        "--study", type=Path, default=Path("results/repo-skills-continuation-20261123")
    )
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "plan":
        if PLAN.exists():
            raise ValueError("Committed continuation plans are not overwritten")
        save(PLAN, make_plan(load_settings().docker))
    elif arguments.command == "run":
        run(arguments.study)
    elif arguments.command == "combine":
        combine(arguments.study, arguments.output or Path("artifacts/repo-skills-20261123"))
    else:
        manifest = json.loads((arguments.study / "manifest.json").read_text(encoding="utf-8"))
        rows = json.loads((arguments.study / "results.json").read_text(encoding="utf-8"))
        export(
            arguments.study,
            arguments.output or Path("artifacts/repo-skills-continuation-20261123"),
            report_extra=comparison_report(manifest["plan"], rows),
        )


if __name__ == "__main__":
    main()
