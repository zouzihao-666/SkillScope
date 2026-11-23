"""Build a fresh phase input; this module neither runs an agent nor retains history."""

from skillscope.models import Condition, Experiment, Stage

BASE_INSTRUCTIONS = """You are working on a Python code repair task.
Follow the task requirements. Skill guides are subordinate to the task requirements.
Work only on the supplied implementation; do not change the independent grader.
Current phase: {stage}.
{phase_instruction}"""

PHASE_INSTRUCTIONS = {
    Stage.INVESTIGATE: "Identify the cause and outline a repair. Do not produce a final patch yet.",
    Stage.IMPLEMENT: "Produce the repaired Python module, preserving the required public interface.",
    Stage.VERIFY: "Review the candidate against the requirements and identify remaining failures.",
}


def build_messages(
    experiment: Experiment,
    task_id: str,
    condition: Condition,
    stage: Stage,
) -> list[dict[str, str]]:
    task = next((task for task in experiment.tasks if task.id == task_id), None)
    if task is None:
        raise ValueError(f"unknown task: {task_id}")
    skills = {skill.id: skill for skill in experiment.skills}
    if len(set(condition.skill_ids)) != len(condition.skill_ids):
        raise ValueError("duplicate skills in condition")
    missing = set(condition.skill_ids) - skills.keys()
    if missing:
        raise ValueError(f"unknown skills: {', '.join(sorted(missing))}")
    active = [
        skills[id_]
        for id_ in condition.skill_ids
        if condition.policy == "global" or stage in skills[id_].stages
    ]
    system = BASE_INSTRUCTIONS.format(
        stage=stage.value, phase_instruction=PHASE_INSTRUCTIONS[stage]
    )
    for skill in active:
        system += f"\n\n--- Skill guide: {skill.id} ---\n{skill.text}"
    user = (
        f"Task: {task.id}\n\n{task.instruction}\n\nStarter module:\n```python\n{task.starter}\n```"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
