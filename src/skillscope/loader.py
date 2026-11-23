"""Read and fingerprint the complete input, including the independent grader."""

import hashlib
import json
from pathlib import Path

from skillscope.models import Experiment, ExperimentSpec, Skill, Task


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_input(root: Path, relative: Path) -> str:
    target = (root / relative).resolve()
    if relative.is_absolute() or not target.is_relative_to(root):
        raise ValueError(f"input must stay inside experiment directory: {relative}")
    text = target.read_text(encoding="utf-8-sig")
    if not text.strip():
        raise ValueError(f"input file is empty: {relative}")
    return text


def load_experiment(config: Path) -> Experiment:
    config = config.resolve()
    spec = ExperimentSpec.model_validate_json(config.read_text(encoding="utf-8-sig"))
    root = config.parent
    skills = []
    for item in spec.skills:
        text = read_input(root, item.file)
        skills.append(Skill(id=item.id, stages=item.stages, text=text, sha256=digest(text)))
    tasks = []
    for item in spec.tasks:
        content = {
            "id": item.id,
            "split": item.split,
            "instruction": read_input(root, item.instruction_file),
            "starter": read_input(root, item.starter_file),
            "grader_sha256": digest(read_input(root, item.grader_file)),
        }
        tasks.append(Task(**content, sha256=digest(canonical_json(content))))
    payload = {
        "name": spec.name,
        "model": spec.model,
        "skills": [item.model_dump(mode="json") for item in skills],
        "tasks": [item.model_dump(mode="json") for item in tasks],
    }
    return Experiment(**payload, sha256=digest(canonical_json(payload)))
