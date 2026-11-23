"""Offline analysis and portable, credential-audited workflow evidence export."""

import gzip
import hashlib
import json
import re
from pathlib import Path

from skillscope.batch import write_json
from skillscope.presentation import workflow_report, write_report


def audited_files(directory: Path):
    expected = json.loads((directory / "checksums.json").read_text(encoding="utf-8"))
    for name, checksum in expected.items():
        if Path(name).name != name or "/" in name or "\\" in name:
            raise ValueError("Invalid evidence inventory")
        if hashlib.sha256((directory / name).read_bytes()).hexdigest() != checksum:
            raise ValueError(f"Evidence checksum mismatch: {name}")


def analyze_evidence(directory: Path, output: Path) -> dict:
    audited_files(directory)
    report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    groups = report["conditions"]
    skills = manifest["plan"]["skills"]
    suspect = [
        key.removeprefix("single-")
        for key, group in groups.items()
        if key.startswith("single-")
        and group["valid_final_grades"] >= 3
        and group["passed"] * 3 <= group["valid_final_grades"]
    ]
    from skillscope.diagnostics import policy_from_suspects

    ids = tuple(value["id"] for value in skills)
    declared = {value["id"]: tuple(value["stages"]) for value in skills}
    policy = {
        "status": "proposed_not_independently_validated",
        "phases": policy_from_suspects(ids, declared, tuple(suspect)),
        "basis": "historical single-skill outcomes; a new diagnosis must confirm them with fresh runs",
        "suspects": suspect,
    }
    rows = [
        {
            "task": ", ".join(manifest["plan"]["workspace_sha256"]),
            "role": key,
            "passed": value["passed"],
            "failed": value["functional_failures"],
            "unresolved": value["recorded"] - value["valid_final_grades"],
        }
        for key, value in groups.items()
    ]
    result = {
        "title": "已有实验的诊断概览",
        "summary": "已读取真实历史记录；本命令没有新模型调用。低表现单技能列为待复核对象，阶段方案尚未独立验证。",
        "comparisons": rows,
        "diagnoses": [
            {
                "task": ", ".join(manifest["plan"]["workspace_sha256"]),
                "classification": "inconclusive",
                "suspects": suspect,
            }
        ],
        "policy": policy,
        "budget": {
            key: report.get(key)
            for key in (
                "calls",
                "reported_tokens",
                "usage_complete",
                "estimated_usd_upper",
                "unknown_usage_reserved_usd_upper",
                "conservative_cost_bound_usd",
            )
        },
    }
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "analysis.json", result)
    write_json(output / "policy.json", policy)
    write_report(output, result)
    return result


def export_workflow(root: Path, output: Path):
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    if state["status"] == "running":
        raise ValueError("Cannot publish a running workflow")
    plan_raw = (root / "plan.json").read_bytes()
    if hashlib.sha256(plan_raw).hexdigest() != state["plan_sha256"]:
        raise ValueError("Workflow plan checksum changed")
    plan = json.loads(plan_raw)
    task_fingerprints = {value["id"]: value["fingerprint"] for value in plan["tasks"]}
    workflow_report(root)
    records = []
    for trial in state["trials"]:
        directory = root / "runs" / trial["id"]
        trace_path = directory / "trace.jsonl"
        trace = (
            [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
            if trace_path.exists()
            else []
        )
        result = trial.get("result")
        if result and (
            result.get("source_sha256") != plan["source_sha256"]
            or result.get("initial_workspace_sha256") != task_fingerprints[trial["task"]]
        ):
            raise ValueError("Run source or task differs from its frozen plan")
        if (
            result
            and len([event for event in trace if event["type"] == "request"])
            != result["calls_attempted"]
        ):
            raise ValueError("Trace count differs from trial metadata")
        workspace = directory / "workspace-final.json"
        records.append(
            {
                "trial": trial,
                "trace": trace,
                "workspace": json.loads(workspace.read_text(encoding="utf-8"))
                if workspace.exists()
                else None,
            }
        )
    # Include only frozen task inventories, never the whole project or .env.
    inputs = {
        path.relative_to(root / "inputs").as_posix(): path.read_text(encoding="utf-8")
        for path in (root / "inputs").rglob("*")
        if path.is_file()
    }
    raw = json.dumps({"records": records, "inputs": inputs}, ensure_ascii=False).encode()
    selected = [
        name
        for name in (
            "plan.json",
            "state.json",
            "policy.json",
            "policy-validation.json",
            "report.md",
            "report.html",
        )
        if (root / name).exists()
    ]
    to_scan = raw + b"".join((root / name).read_bytes() for name in selected)
    if re.search(
        rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})",
        to_scan,
    ):
        raise ValueError("Credential-like content found; export aborted")
    output.mkdir(parents=True, exist_ok=False)
    for name in selected:
        # Keep the exact bytes used by frozen plan and policy hashes.
        (output / name).write_bytes((root / name).read_bytes())
    with (output / "raw-workflow.json.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as archive:
            archive.write(raw)
    checksums = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.iterdir())
    }
    (output / "checksums.json").write_bytes((json.dumps(checksums, indent=2) + "\n").encode())
    return {"files": len(checksums), "trials": len(state["trials"]), "status": state["status"]}
