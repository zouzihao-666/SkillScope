"""Portable repository diagnosis configuration and immutable input snapshots."""

import json
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from skillscope.batch import source_fingerprint
from skillscope.loader import digest
from skillscope.models import Identifier, Record, Skill, SkillSpec
from skillscope.repository.workspace import Workspace, trusted_file


class RepositoryTask(Record):
    id: Identifier
    manifest: Path
    split: Literal["discovery", "holdout"] = "discovery"


class DiagnosisLimits(Record):
    max_calls: int = Field(default=360, ge=3, le=10000)
    max_runs: int = Field(default=36, ge=1, le=1000)
    max_usd: float = Field(default=2.0, gt=0, allow_inf_nan=False)
    per_run_calls: int = Field(default=10, ge=3, le=10)
    per_phase_calls: int = Field(default=4, ge=1, le=4)
    max_subset_evaluations: int = Field(default=8, ge=1, le=100)


class DiagnosisSpec(Record):
    schema_version: Literal[1] = 1
    name: Identifier
    model: Literal["deepseek-flash"] = "deepseek-flash"
    skills: tuple[SkillSpec, ...] = Field(min_length=1)
    tasks: tuple[RepositoryTask, ...] = Field(min_length=1)
    repeats: int = Field(default=3, ge=3, le=10)
    limits: DiagnosisLimits = Field(default_factory=DiagnosisLimits)
    prior_evidence: Path | None = None
    validate_holdout: bool = False

    @model_validator(mode="after")
    def check_inventory(self):
        for label, values in (("skills", self.skills), ("tasks", self.tasks)):
            if len({item.id for item in values}) != len(values):
                raise ValueError(f"Duplicate {label} identifiers")
        if not any(task.split == "discovery" for task in self.tasks):
            raise ValueError("At least one discovery task is required")
        return self


def local_path(root: Path, path: Path) -> Path:
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Configuration paths must stay under the configuration directory")
    result = root / path
    current = root
    for part in path.parts:
        current /= part
        if current.is_symlink():
            raise ValueError("Symlinked configuration inputs are unsupported")
    if not result.resolve().is_relative_to(root):
        raise ValueError("Configuration input leaves its root")
    return result


def load_repository_config(config: Path) -> tuple[DiagnosisSpec, dict, dict]:
    root = config.resolve().parent
    spec = DiagnosisSpec.model_validate_json(config.read_text(encoding="utf-8-sig"))
    loaded_skills = []
    for item in spec.skills:
        text = trusted_file(root, item.file.as_posix())
        loaded_skills.append(Skill(id=item.id, stages=item.stages, text=text, sha256=digest(text)))
    skills = tuple(loaded_skills)
    tasks, payloads = [], {}
    for task in spec.tasks:
        manifest = local_path(root, task.manifest)
        workspace = Workspace(manifest)
        if workspace.task_id != task.id:
            raise ValueError("Task ID differs from its manifest")
        task_data = {
            "schema_version": 1,
            "id": task.id,
            "execution_mode": workspace.execution_mode,
            "project": "project",
            "visible": [item["path"] for item in workspace.list_files()],
            "editable": sorted(workspace.editable),
            "instruction": "instruction.md",
            "adapter": "adapter.py",
            "public_grader": "public_tests.py",
            "hidden_grader": "hidden_tests.py",
        }
        payloads[task.id] = {
            "manifest": task_data,
            "files": {
                item["path"]: workspace.read_file(item["path"]) for item in workspace.list_files()
            },
            "instruction.md": workspace.instruction,
            "adapter.py": workspace.adapter,
            "public_tests.py": workspace.public_grader,
            "hidden_tests.py": workspace.hidden_grader,
        }
        tasks.append(
            {
                "id": task.id,
                "split": task.split,
                "fingerprint": workspace.initial_fingerprint,
                "instruction": workspace.instruction,
            }
        )
    prior = None
    if spec.prior_evidence:
        directory = local_path(root, spec.prior_evidence)
        # Historical measurements only prioritize fresh confirmation, never fill
        # a new measurement's successful or failed counts.
        checksums = json.loads((directory / "checksums.json").read_text(encoding="utf-8"))
        import hashlib

        for name in ("manifest.json", "results.json", "report.json"):
            if hashlib.sha256((directory / name).read_bytes()).hexdigest() != checksums[name]:
                raise ValueError("Prior evidence checksum mismatch")
        original = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))["plan"]
        report = json.loads((directory / "report.json").read_text(encoding="utf-8"))
        if {skill.id: skill.sha256 for skill in skills} != {
            value["id"]: value["sha256"] for value in original["skills"]
        }:
            raise ValueError("Prior evidence used different guide text")
        prior = {
            "sha256": digest((directory / "report.json").read_text(encoding="utf-8")),
            "tasks": original["workspace_sha256"],
            "conditions": report["conditions"],
        }
    portable_spec = spec.model_dump(mode="json")
    for value, item in zip(portable_spec["skills"], spec.skills, strict=True):
        value["file"] = item.file.as_posix()
    for value, item in zip(portable_spec["tasks"], spec.tasks, strict=True):
        value["manifest"] = item.manifest.as_posix()
    if spec.prior_evidence:
        portable_spec["prior_evidence"] = spec.prior_evidence.as_posix()
    value = {
        "spec": portable_spec,
        "skills": [skill.model_dump(mode="json") for skill in skills],
        "tasks": tasks,
        "prior": prior,
        "source_sha256": source_fingerprint(),
        "algorithm": "repeated_regression_reduction_and_declared_scope_repair_v1",
        "evidence_note": "Single-skill harm and combination interaction are separate labels. Small repeated samples are exploratory, not significance or causality proof.",
    }
    value["input_sha256"] = digest(
        json.dumps(
            {"spec": value["spec"], "skills": value["skills"], "tasks": tasks, "prior": prior},
            sort_keys=True,
            ensure_ascii=False,
        )
    )
    return spec, value, payloads


def freeze_repository_inputs(root: Path, payloads: dict) -> None:
    for task_id, payload in payloads.items():
        task_root = root / task_id
        task_root.mkdir(parents=True, exist_ok=False)
        (task_root / "task.json").write_bytes(
            (json.dumps(payload["manifest"], indent=2) + "\n").encode()
        )
        for name, text in payload.items():
            if name not in ("manifest", "files"):
                (task_root / name).write_bytes(text.encode())
        for name, text in payload["files"].items():
            path = task_root / "project" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode())
