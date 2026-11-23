"""Descriptive estimates; no causal or population claim from correlated repetitions."""

import json
import math
from collections import Counter
from pathlib import Path

from skillscope.batch import write_json

KNOWN = {"passed", "failed", "invalid_output", "timeout", "budget_exhausted"}


def wilson(successes: int, total: int) -> list[float] | None:
    if not 0 <= successes <= total:
        raise ValueError("Invalid counts")
    if not total:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - half), min(1.0, center + half)]


def summarize(rows: list[dict], planned: int) -> dict:
    counts = Counter(row["status"] for row in rows)
    success = counts["passed"]
    known = sum(counts[name] for name in KNOWN)
    unknown = planned - known
    return {
        "planned": planned,
        "recorded": len(rows),
        "status_counts": dict(counts),
        "successes": success,
        "known_model_outcomes": known,
        "unknown_or_missing": unknown,
        "completion_rate_known": success / known if known else None,
        "completion_bounds_missing": [success / planned, (success + unknown) / planned]
        if planned
        else None,
        "wilson_95_descriptive": wilson(success, known),
        "calls": sum(row["calls_attempted"] for row in rows),
        "reported_tokens": sum(row["reported_tokens"]["total_tokens"] for row in rows),
        "estimated_usd_upper": sum(row["estimated_usd_upper"] for row in rows),
    }


def build_report(batch: Path) -> dict:
    manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
    rows = [
        json.loads(line)
        for line in (batch / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    ids = [row["job"]["id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate run records")
    jobs = {job["id"]: job for job in manifest["plan"]["runs"]}
    main = [row for row in rows if row["job"]["phase"] == "main"]
    for row in main:
        job = jobs.get(row["job"]["id"])
        if job is None or any(
            row["job"][key] != job[key] for key in ("task_id", "condition_id", "repeat")
        ):
            raise ValueError("Run does not match the frozen plan")
        if row["experiment_sha256"] != manifest["experiment_sha256"]:
            raise ValueError("Mixed experiment fingerprints")
    tasks = [item["id"] for item in manifest["plan"]["tasks"]]
    repeats = manifest["plan"]["repeats"]
    conditions = [item["id"] for item in manifest["plan"]["conditions"]]
    groups, matrix, comparisons = {}, {}, {}
    indexed = {
        (row["job"]["task_id"], row["job"]["condition_id"], row["job"]["repeat"]): row
        for row in main
    }
    for condition in conditions:
        selected = [row for row in main if row["job"]["condition_id"] == condition]
        groups[condition] = summarize(selected, len(tasks) * repeats)
        matrix[condition] = {}
        wins = losses = ties = unavailable = 0
        for task in tasks:
            matrix[condition][task] = summarize(
                [row for row in selected if row["job"]["task_id"] == task], repeats
            )
            if condition == "baseline":
                continue
            for repeat in range(1, repeats + 1):
                left, right = (
                    indexed.get((task, "baseline", repeat)),
                    indexed.get((task, condition, repeat)),
                )
                if (
                    not left
                    or not right
                    or left["status"] not in KNOWN
                    or right["status"] not in KNOWN
                ):
                    unavailable += 1
                    continue
                a, b = left["status"] == "passed", right["status"] == "passed"
                wins += b and not a
                losses += a and not b
                ties += a == b
        if condition != "baseline":
            comparisons[condition] = {
                "paired_wins": wins,
                "paired_losses": losses,
                "paired_ties": ties,
                "unavailable_pairs": unavailable,
                "delta_on_available_pairs": (wins - losses) / (wins + losses + ties)
                if wins + losses + ties
                else None,
            }
    singles = [name for name in conditions if name.startswith("single-")]
    candidates = []
    for task in tasks:
        if matrix["baseline"][task]["successes"] != repeats:
            continue
        if any(matrix[name][task]["successes"] != repeats for name in singles):
            continue
        combined = matrix["all"][task]
        if combined["known_model_outcomes"] != repeats or combined["successes"] > repeats - 2:
            continue
        candidates.append(
            {
                "task": task,
                "kind": "repeated_regression_candidate_not_confirmed_cause",
                "all_successes": combined["successes"],
                "length_controls_all_pass": all(
                    matrix[name][task]["successes"] == repeats for name in ("length-a", "length-b")
                ),
                "reverse_successes": matrix["all-reversed"][task]["successes"],
                "scoped_successes": matrix["scoped"][task]["successes"],
            }
        )
    return {
        "schema_version": 1,
        "experiment_sha256": manifest["experiment_sha256"],
        "plan_sha256": manifest["plan_sha256"],
        "main_runs_planned": len(jobs),
        "main_runs_recorded": len(main),
        "pilot_runs": sum(row["job"]["phase"] == "pilot" for row in rows),
        "groups": groups,
        "per_task": matrix,
        "comparisons_to_baseline": comparisons,
        "candidate_combinations": candidates,
        "conclusion": "repeated_regression_candidates_require_confirmation"
        if candidates
        else "insufficient_evidence_of_stable_skill_combination_regression",
        "missing_outcomes": sum(group["unknown_or_missing"] for group in groups.values()),
        "all_usage_complete": all(row["usage_complete"] for row in rows),
        "totals_including_pilot": summarize(rows, len(jobs) + len(manifest["pilot"]["tasks"])),
        "limitations": [
            "Manually authored teaching skills and four fixed discovery tasks, not a representative sample.",
            "Repetitions can correlate at temperature zero and with caching.",
            "Wilson intervals assume independent Bernoulli observations and are descriptive only.",
            "Task/repetition matching does not share a provider-side random seed.",
            "Controls match characters, not tokenizer counts; passages and skill labels can influence output.",
            "Model response aliases do not establish a pinned server-side weight revision.",
            "Peak-rate estimates are not account invoices.",
        ],
    }


def render_markdown(report: dict) -> str:
    def pct(value):
        return "未知" if value is None else f"{value:.1%}"

    lines = [
        "# SkillScope 第三阶段实验报告",
        "",
        f"主实验计划 {report['main_runs_planned']} 次，记录 {report['main_runs_recorded']} 次；"
        f"另有 {report['pilot_runs']} 次基线预检，不进入主对照统计。",
        "",
        "| 配置 | 成功/可判定 | 未知或缺失 | 完成率 | Wilson 95% 描述区间 | 调用 | tokens | 高峰价上界估算 USD |",
        "| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for name, group in report["groups"].items():
        interval = group["wilson_95_descriptive"]
        text = "未知" if interval is None else f"{pct(interval[0])}–{pct(interval[1])}"
        lines.append(
            f"| {name} | {group['successes']}/{group['known_model_outcomes']} | "
            f"{group['unknown_or_missing']} | {pct(group['completion_rate_known'])} | {text} | "
            f"{group['calls']} | {group['reported_tokens']} | {group['estimated_usd_upper']:.6f} |"
        )
    tasks = list(report["per_task"]["baseline"])
    lines += [
        "",
        "## 各任务重复结果",
        "",
        "| 配置 | " + " | ".join(tasks) + " |",
        "| --- | " + " | ".join("---:" for _ in tasks) + " |",
    ]
    for name, entries in report["per_task"].items():
        values = [
            f"{entries[task]['successes']}/{entries[task]['planned']}（未知 {entries[task]['unknown_or_missing']}）"
            for task in tasks
        ]
        lines.append(f"| {name} | " + " | ".join(values) + " |")
    lines += [
        "",
        "## 与基线对应比较",
        "",
        "| 配置 | 改善 | 退化 | 相同 | 无法比较 |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for name, item in report["comparisons_to_baseline"].items():
        lines.append(
            f"| {name} | {item['paired_wins']} | {item['paired_losses']} | "
            f"{item['paired_ties']} | {item['unavailable_pairs']} |"
        )
    lines += ["", "## 结论与边界", ""]
    if report["candidate_combinations"]:
        lines.append("观察到重复退化候选，尚不能据此确认组合冲突原因：")
        for item in report["candidate_combinations"]:
            lines.append(
                f"- {item['task']}：基线及所有单技能通过全部重复，全部加载通过 "
                f"{item['all_successes']} 次；两种长度对照均通过：{item['length_controls_all_pass']}。"
            )
    else:
        lines.append(
            "当前证据不足以确认稳定的技能组合退化。需结合逐题结果检查任务天花板效应、"
            "单技能本身的影响、预算和样本量，不能改写成已发现冲突。"
        )
    total = report["totals_including_pilot"]
    lines += [
        "",
        f"含预检：{total['calls']} 次模型调用，{total['reported_tokens']} tokens，"
        f"高峰价上界估算 USD {total['estimated_usd_upper']:.6f}，并非账户账单。",
        "",
        "无效模型输出、代码超时、预算耗尽计入任务失败；API、环境错误与缺失结果保持未知。",
        "",
        "Wilson 区间使用独立伯努利近似，仅作描述；固定任务的相关重复不能支持新任务总体推断。"
        "对应比较按题目和重复编号匹配，不代表共享模型随机种子。字符等长不等于 token 等长，无关文本也可能影响模型。",
        "",
        "本研究仅覆盖人工编写的教学技能和函数任务。模型为 deepseek-flash 非思考模式，"
        "返回别名不保证权重版本固定。未对 holdout 调用模型。",
        "",
    ]
    return "\n".join(lines)


def save_report(batch: Path) -> dict:
    report = build_report(batch)
    write_json(batch / "report.json", report)
    (batch / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report
