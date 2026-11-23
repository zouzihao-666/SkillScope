"""A preregistered output-cap follow-up, reusing the frozen three-phase runner."""

import argparse
import json
import random
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict
from pathlib import Path

from skillscope.batch import (
    PRICE,
    Limits,
    can_start,
    freeze_config,
    source_fingerprint,
    trace_cost,
    write_json,
)
from skillscope.loader import canonical_json, digest, load_experiment
from skillscope.runner import run_task
from skillscope.sandbox import preflight
from skillscope.settings import Settings, load_settings

CONDITIONS = ("baseline", "all", "all-reversed", "scoped")
CAPS = (1024, 2048)


def make_plan(repeats: int = 5, seed: int = 1041) -> dict:
    if repeats < 2:
        raise ValueError("At least two repetitions required")
    jobs = [
        {
            "id": f"get-path__{condition}__cap{cap}__{repeat:03d}",
            "task_id": "get-path",
            "condition_id": condition,
            "cap": cap,
            "repeat": repeat,
        }
        for repeat in range(1, repeats + 1)
        for cap in CAPS
        for condition in CONDITIONS
    ]
    random.Random(seed).shuffle(jobs)
    return {
        "task": "get-path",
        "conditions": list(CONDITIONS),
        "caps": list(CAPS),
        "repeats": repeats,
        "seed": seed,
        "runs": jobs,
    }


def summarize(output: Path) -> dict:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (output / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    groups = {}
    for condition in CONDITIONS:
        for cap in CAPS:
            selected = [
                row
                for row in rows
                if row["job"]["condition_id"] == condition and row["job"]["cap"] == cap
            ]
            groups[f"{condition}/{cap}"] = {
                "recorded": len(selected),
                "planned": manifest["plan"]["repeats"],
                "passed": sum(row["status"] == "passed" for row in selected),
                "length_truncations": sum(row["length_truncation"] for row in selected),
                "other_model_failures": sum(
                    row["status"] in ("failed", "invalid_output", "timeout", "budget_exhausted")
                    and not row["length_truncation"]
                    for row in selected
                ),
                "unknown": sum(
                    row["status"]
                    in ("api_error", "infrastructure_error", "internal_error", "interrupted")
                    for row in selected
                )
                + manifest["plan"]["repeats"]
                - len(selected),
                "tokens": sum(row["reported_tokens"]["total_tokens"] for row in selected),
                "estimated_usd_upper": sum(row["estimated_usd_upper"] for row in selected),
            }
    patterns = [
        condition
        for condition in CONDITIONS
        if groups[f"{condition}/1024"]["length_truncations"] >= 2
        and groups[f"{condition}/2048"]["length_truncations"] == 0
        and groups[f"{condition}/2048"]["passed"] == manifest["plan"]["repeats"]
    ]
    result = {
        "groups": groups,
        "observed_budget_sensitive_candidates": patterns,
        "conclusion": "budget_sensitive_candidates_need_confirmation"
        if patterns
        else "no_repeated_budget_sensitive_pattern_observed",
    }
    write_json(output / "report.json", result)
    lines = [
        "# 输出预算敏感性复核",
        "",
        "| 配置 | 每阶段上限 | 通过/计划 | 长度截断 | 其他模型失败 | 未知/缺失 | tokens |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for condition in CONDITIONS:
        for cap in CAPS:
            group = groups[f"{condition}/{cap}"]
            lines.append(
                f"| {condition} | {cap} | {group['passed']}/{group['planned']} | "
                f"{group['length_truncations']} | {group['other_model_failures']} | "
                f"{group['unknown']} | {group['tokens']} |"
            )
    lines += [
        "",
        "本实验只覆盖第三阶段 get-path 教学题，使用新的独立调用；没有替换第三阶段数据。",
        "两档上限都应用于全部三个阶段，不能单独归因于调查阶段。重复编号不共享模型随机种子。",
        "5 次重复不足以证明总体可靠性；未观察到重复模式不等于已证明没有预算影响。",
        "",
    ]
    if patterns:
        lines.append("观察到待复核的预算敏感模式：" + ", ".join(patterns))
    else:
        lines.append("未观察到满足预先规则的重复预算敏感模式；不把单次旧截断升级为稳定冲突。")
    lines.append("")
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def execute(
    config: Path,
    settings: Settings,
    output: Path,
    repeats: int = 5,
    seed: int = 1041,
    workers: int = 2,
) -> dict:
    plan = make_plan(repeats, seed)
    limits = Limits(
        max_calls=len(plan["runs"]) * 3,
        max_reported_tokens=500000,
        max_estimated_usd=0.50,
        max_output_tokens=max(CAPS),
        workers=workers,
    )
    limits.validate()
    experiment = load_experiment(config)
    if experiment.model != "deepseek-flash":
        raise ValueError("The fixed price schedule only covers deepseek-flash")
    if not any(task.id == "get-path" and task.split == "discovery" for task in experiment.tasks):
        raise ValueError("The discovery get-path task is required")
    image = preflight(settings.docker)
    output.mkdir(parents=True, exist_ok=False)
    frozen = freeze_config(config, output / "frozen")
    manifest = {
        "schema_version": 1,
        "plan": plan,
        "plan_sha256": digest(canonical_json(plan)),
        "limits": asdict(limits),
        "pricing": PRICE,
        "sandbox_image_id": image,
        "experiment_sha256": experiment.sha256,
        "source_sha256": source_fingerprint(),
        "study_script_sha256": digest(Path(__file__).read_text(encoding="utf-8")),
        "protocol": "docs/next-steps.md; whole-pipeline per-stage output-cap comparison",
    }
    write_json(output / "manifest.json", manifest)
    rows = []
    status, reason = "running", None

    def checkpoint():
        write_json(
            output / "study.json",
            {
                "status": status,
                "stop_reason": reason,
                "completed": len(rows),
                "planned": len(plan["runs"]),
                "calls_attempted": sum(row["calls_attempted"] for row in rows),
                "reported_tokens": sum(row["reported_tokens"]["total_tokens"] for row in rows),
                "estimated_usd_upper": sum(row["estimated_usd_upper"] for row in rows),
                "usage_complete": all(row["usage_complete"] for row in rows),
            },
        )
        with (output / "results.jsonl").open("w", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    def run(job):
        directory = output / "runs" / job["id"]
        result = run_task(
            frozen,
            job["task_id"],
            job["condition_id"],
            settings,
            directory,
            max_tokens=job["cap"],
            quiet=True,
        )
        if result["sandbox_image_id"] != image:
            raise ValueError("Sandbox image changed")
        trace = [
            json.loads(line)
            for line in (directory / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        length = any(
            event["type"] == "response"
            and any(choice["finish_reason"] == "length" for choice in event["response"]["choices"])
            for event in trace
        )
        return {
            **result,
            "job": job,
            "length_truncation": length,
            "estimated_usd_upper": trace_cost(directory, result),
        }

    try:
        index = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {}
            while index < len(plan["runs"]) or pending:
                while (
                    status == "running"
                    and index < len(plan["runs"])
                    and len(pending) < workers
                    and can_start(rows, len(pending), limits)
                ):
                    job = plan["runs"][index]
                    pending[pool.submit(run, job)] = job
                    index += 1
                if not pending:
                    if index < len(plan["runs"]):
                        status, reason = "stopped", "budget_reservation_limit"
                    break
                done, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    job = pending.pop(future)
                    try:
                        result = future.result()
                    except Exception:
                        status, reason = "stopped", f"worker_error:{job['id']}; no paid retry"
                        continue
                    rows.append(result)
                    print(
                        f"预算复核 {len(rows)}/{len(plan['runs'])}：{job['id']} {result['status']}",
                        flush=True,
                    )
                    if not result["usage_complete"] or result["status"] in (
                        "api_error",
                        "infrastructure_error",
                        "internal_error",
                        "interrupted",
                    ):
                        status, reason = "stopped", "unknown_usage_or_external_failure"
                    checkpoint()
                if status != "running" and not pending:
                    break
        if status == "running":
            status = "completed" if len(rows) == len(plan["runs"]) else "stopped"
    except BaseException:
        status, reason = "interrupted", "inspect_records_before_any_new_paid_run"
        raise
    finally:
        checkpoint()
        summarize(output)
    return json.loads((output / "study.json").read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("benchmarks/stage3/experiment.json"))
    parser.add_argument("--output", type=Path, default=Path("results/budget-study-20261123"))
    arguments = parser.parse_args()
    result = execute(arguments.config, load_settings(), arguments.output)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
