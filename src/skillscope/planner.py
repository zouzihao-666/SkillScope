"""Plan comparisons without pretending to execute or score a model."""

import random
from typing import Literal

from skillscope.models import Condition, Experiment, PlannedRun, Stage


def conditions_for(experiment: Experiment) -> tuple[Condition, ...]:
    ids = tuple(skill.id for skill in experiment.skills)
    return (
        Condition(id="baseline", policy="global", skill_ids=()),
        *(Condition(id=f"single-{id_}", policy="global", skill_ids=(id_,)) for id_ in ids),
        Condition(id="all", policy="global", skill_ids=ids),
        Condition(id="scoped", policy="scoped", skill_ids=ids),
    )


def build_plan(
    experiment: Experiment,
    repeats: int = 3,
    seed: int = 42,
    split: Literal["discovery", "holdout"] = "discovery",
    max_runs: int = 1000,
) -> dict:
    if repeats < 1 or max_runs < 1:
        raise ValueError("repeats and max_runs must be positive")
    if split not in ("discovery", "holdout"):
        raise ValueError(f"unknown split: {split}")
    tasks = tuple(task for task in experiment.tasks if task.split == split)
    if not tasks:
        raise ValueError(f"no tasks in split: {split}")
    conditions = conditions_for(experiment)
    count = len(tasks) * len(conditions) * repeats
    if count > max_runs:
        raise ValueError(f"plan needs {count} runs, exceeding max_runs={max_runs}")
    runs = [
        PlannedRun(
            id=f"{task.id}__{condition.id}__{repeat:03d}",
            task_id=task.id,
            condition_id=condition.id,
            repeat=repeat,
        )
        for repeat in range(1, repeats + 1)
        for task in tasks
        for condition in conditions
    ]
    random.Random(seed).shuffle(runs)
    # Store selected task/skill text, not just paths that may change after planning.
    return {
        "schema_version": 1,
        "status": "planned_not_executed",
        "experiment": experiment.name,
        "experiment_sha256": experiment.sha256,
        "model_requested": experiment.model,
        "thinking": "disabled",
        "split": split,
        "repeats": repeats,
        "order_seed": seed,
        "stages": [stage.value for stage in Stage],
        "run_count": len(runs),
        "skills": [skill.model_dump(mode="json") for skill in experiment.skills],
        "tasks": [task.model_dump(mode="json") for task in tasks],
        "conditions": [condition.model_dump(mode="json") for condition in conditions],
        "runs": [run.model_dump(mode="json") for run in runs],
    }
