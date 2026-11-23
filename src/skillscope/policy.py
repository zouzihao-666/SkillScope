"""Apply a frozen, selected policy to a new task without repeating diagnosis."""

import difflib
import hashlib
import json
from pathlib import Path

from skillscope.batch import write_json
from skillscope.models import Condition, Skill, Stage
from skillscope.presentation import write_report
from skillscope.repository.agent import run_agent
from skillscope.repository.workspace import Workspace
from skillscope.sandbox import materialize_project
from skillscope.settings import Settings


def load_saved_policy(study: Path):
    plan_bytes = (study / "plan.json").read_bytes()
    policy_bytes = (study / "policy.json").read_bytes()
    state = json.loads((study / "state.json").read_text(encoding="utf-8"))
    if state["status"] == "running":
        raise ValueError("Wait for the diagnosis to finish before applying its policy")
    if hashlib.sha256(plan_bytes).hexdigest() != state["plan_sha256"]:
        raise ValueError("Saved plan checksum mismatch")
    if hashlib.sha256(policy_bytes).hexdigest() != state.get("policy_frozen_sha256"):
        raise ValueError("Policy is unvalidated or its frozen bytes changed")
    plan, policy = json.loads(plan_bytes), json.loads(policy_bytes)
    skills = tuple(Skill.model_validate(value) for value in plan["skills"])
    ids = tuple(skill.id for skill in skills)
    phases = policy["phases"]
    if set(phases) != {stage.value for stage in Stage} or any(
        value != [id_ for id_ in ids if id_ in value] for value in phases.values()
    ):
        raise ValueError("Saved policy changed guide identities or order")
    actual = tuple(
        skill.model_copy(
            update={"stages": tuple(stage for stage in Stage if skill.id in phases[stage.value])}
        )
        for skill in skills
    )
    condition = Condition(
        id="saved-policy",
        policy="scoped",
        skill_ids=tuple(skill.id for skill in actual if skill.stages),
    )
    return plan, policy, actual, condition, hashlib.sha256(policy_bytes).hexdigest()


def apply_saved_policy(study: Path, task: Path, settings: Settings, output: Path):
    plan, policy, skills, condition, checksum = load_saved_policy(study)
    workspace = Workspace(task)
    limits = plan["spec"]["limits"]
    result = run_agent(
        task,
        settings,
        output,
        skills=skills,
        condition=condition,
        max_requests=limits["per_run_calls"],
        per_phase_requests=limits["per_phase_calls"],
    )
    snapshot = json.loads((output / "workspace-final.json").read_text(encoding="utf-8"))
    candidate_root = output / "candidate"
    candidate_root.mkdir()
    materialize_project(candidate_root, snapshot)
    patch = []
    for path in sorted(workspace.editable):
        patch.extend(
            difflib.unified_diff(
                workspace.read_file(path).splitlines(keepends=True),
                snapshot[path].splitlines(keepends=True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
    (output / "changes.patch").write_bytes("".join(patch).encode())
    applied = {
        "source_policy_sha256": checksum,
        "phases": policy["phases"],
        "source_task": policy.get("source_task"),
        "current_task": workspace.task_id,
        "task_fingerprint": workspace.initial_fingerprint,
        "note": "A new task evaluation using a fixed policy; no diagnosis or policy retuning performed.",
        "candidate_directory": "candidate",
        "patch_file": "changes.patch",
    }
    write_json(output / "applied-policy.json", applied)
    valid = isinstance(result.get("grading"), dict) and result["grading"].get("status") in (
        "passed",
        "failed",
    )
    write_report(
        output,
        {
            "title": f"{workspace.task_id}：应用已保存方案",
            "summary": f"运行状态：{result['status']}。使用冻结方案直接执行新任务，没有重新搜索或调参。",
            "comparisons": [
                {
                    "task": workspace.task_id,
                    "role": "已保存方案",
                    "passed": int(valid and result["status"] == "passed"),
                    "failed": int(valid and result["status"] == "failed"),
                    "unresolved": int(not valid),
                }
            ],
            "policy": applied,
            "budget": {
                "calls_attempted": result["calls_attempted"],
                "usage_complete": result["usage_complete"],
                "estimated_usd_upper": result["estimated_usd_upper"],
            },
        },
    )
    return result
