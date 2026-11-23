"""Readable, self-contained reports; model or guide text is always HTML-escaped."""

import html
import json
from pathlib import Path

STATUS = {
    "completed": "执行完成",
    "planned": "仅生成方案",
    "ready": "已准备",
    "running": "运行中",
    "budget_exhausted": "已到预算边界",
    "unknown_usage_stopped": "费用未知，已停止",
    "interrupted": "运行中断",
    "single_skill_regression": "重复观察到单技能退化",
    "combination_candidate": "组合额外退化候选",
    "mixture_with_individual_harm_or_unknown": "混合退化，含单技能问题或未知",
    "mixture_regression_unclassified": "混合退化，归因检查未完成",
    "baseline_unreliable": "无技能基线不可靠",
    "not_reproduced": "未复现退化",
    "inconclusive": "证据不足",
}

ROLES = {
    "baseline": "无技能基线",
    "all": "全部加载",
    "fresh_prior_confirmation": "历史疑点的新复核",
    "starting_set": "起始技能集",
    "reduction": "集合缩减",
    "interaction_single_control": "单技能归因检查",
    "generated": "自动生成的阶段方案",
    "manual_scoped": "人工阶段规则",
    "relevance": "相关性筛选",
    "remove_suspects": "移除可疑技能",
    "holdout_baseline": "保留题：无技能",
    "holdout_all": "保留题：全部加载",
    "holdout_selected": "保留题：选定方案",
}


def write_report(output: Path, data: dict) -> None:
    rows = data.get("comparisons", [])
    budget = data.get("budget", {})
    policy = data.get("policy", {})
    lines = [
        f"# {data['title']}",
        "",
        data["summary"],
        "",
        "## 对照结果",
        "",
        "| 任务 | 配置 | 通过 | 功能失败 | 未获有效评分 |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| {row['task']} | {row['role']} | {row['passed']} | {row['failed']} | {row['unresolved']} |"
        )
    lines.extend(
        ["", "同一配置被多个比较角色复用时共享原记录，不计为独立重复。", "", "## 自动诊断", ""]
    )
    for diagnosis in data.get("diagnoses", []):
        lines.append(
            f"- {diagnosis['task']}：{STATUS.get(diagnosis['classification'], diagnosis['classification'])}；可疑技能：{', '.join(diagnosis.get('suspects', [])) or '未确定'}。"
        )
    lines.extend(
        [
            "",
            "## 加载方案",
            "",
            "```json",
            json.dumps(policy, ensure_ascii=False, indent=2),
            "```",
            "",
            "## 费用与限制",
            "",
            json.dumps(budget, ensure_ascii=False, indent=2),
            "",
            "费用为固定价格下的估算，不是账户账单；未收到响应时保留整次预算，不把未知费用算成零。",
            "小规模开发题筛选不能证明普遍因果或统计显著性。生成阶段方案使用已有阶段声明和开发集评分，不等于学习到了最优策略。",
            "",
        ]
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.md").write_bytes("\n".join(lines).encode())

    def esc(value):
        return html.escape(str(value), quote=True)

    body = "".join(
        f"<tr><td>{esc(row['task'])}</td><td>{esc(row['role'])}</td><td>{row['passed']}</td><td>{row['failed']}</td><td>{row['unresolved']}</td></tr>"
        for row in rows
    )
    diagnoses = "".join(
        f"<li><b>{esc(row['task'])}</b>：{esc(STATUS.get(row['classification'], row['classification']))}；可疑技能：{esc(', '.join(row.get('suspects', [])) or '未确定')}</li>"
        for row in data.get("diagnoses", [])
    )
    document = f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(data["title"])}</title>
<style>body{{font:16px/1.7 system-ui,sans-serif;background:#f5f7fa;color:#172638;margin:0}}main{{max-width:1080px;margin:auto;padding:40px 24px}}h1{{font-size:32px}}section{{background:white;border:1px solid #dce3eb;border-radius:12px;padding:24px;margin:20px 0}}table{{border-collapse:collapse;width:100%}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #e7edf3}}th{{color:#46617d}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5f9;padding:16px;border-radius:8px}}.tag{{color:#234b76;background:#e4effc;padding:4px 12px;border-radius:20px}}.note{{color:#506176}}.scroll{{overflow-x:auto}}</style>
<main><span class="tag">SkillScope · 实际记录</span><h1>{esc(data["title"])}</h1><p>{esc(data["summary"])}</p>
<section><h2>对照结果</h2><div class="scroll"><table><thead><tr><th>任务</th><th>配置</th><th>通过</th><th>功能失败</th><th>未获有效评分</th></tr></thead><tbody>{body}</tbody></table></div><p class="note">共享配置会复用已有记录；未获有效评分不当作功能失败。</p></section>
<section><h2>自动诊断</h2><ul>{diagnoses or "<li>尚无足够的新验证记录。</li>"}</ul></section>
<section><h2>阶段加载方案</h2><pre>{esc(json.dumps(policy, ensure_ascii=False, indent=2))}</pre></section>
<section><h2>预算与可信范围</h2><pre>{esc(json.dumps(budget, ensure_ascii=False, indent=2))}</pre><p class="note">费用为估算，不是账单。单个开发题和少量重复不能证明普遍因果；自动生成的阶段方案仍需独立验证。</p></section></main></html>"""
    (output / "report.html").write_bytes(document.encode())


def workflow_report(root: Path) -> dict:
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    rows = []
    for entry in state["measurements"].values():
        value = entry["measurement"]
        rows.append(
            {
                "task": entry["task"],
                "role": ", ".join(ROLES.get(role, role) for role in entry["roles"]),
                "passed": value["passed"],
                "failed": value["failed"],
                "unresolved": value["unresolved"],
                "split": entry["split"],
            }
        )
    policy = {
        **state.get("policy", {"status": "unvalidated"}),
        "holdout_opened": state.get("holdout_opened", False),
        "holdout_validation_record": "policy-validation.json"
        if state.get("holdout_validation")
        else None,
    }
    data = {
        "title": f"{plan['spec']['name']}：自动诊断报告",
        "summary": f"状态：{STATUS.get(state['status'], state['status'])}；已记录 {len(state['trials'])} 次运行。单技能干扰、组合候选和未知情况分别报告。",
        "comparisons": rows,
        "diagnoses": list(state["diagnoses"].values()),
        "policy": policy,
        "budget": state.get("budget", {}),
    }
    write_report(root, data)
    return data
