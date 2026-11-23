"""Validated experiment inputs. Skill order is part of the experiment configuration."""

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]


class Stage(StrEnum):
    INVESTIGATE = "investigate"
    IMPLEMENT = "implement"
    VERIFY = "verify"


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SkillSpec(Record):
    id: Identifier
    file: Path
    stages: tuple[Stage, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_stages(self) -> Self:
        if len(set(self.stages)) != len(self.stages):
            raise ValueError(f"duplicate stages for skill {self.id}")
        return self


class TaskSpec(Record):
    id: Identifier
    split: Literal["discovery", "holdout"]
    instruction_file: Path
    starter_file: Path
    grader_file: Path


class ExperimentSpec(Record):
    schema_version: Literal[1] = 1
    name: Identifier
    model: str = Field(min_length=1)
    skills: tuple[SkillSpec, ...] = Field(min_length=2)
    tasks: tuple[TaskSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        for label, items in (("skill", self.skills), ("task", self.tasks)):
            ids = [item.id for item in items]
            if len(set(ids)) != len(ids):
                raise ValueError(f"duplicate {label} ids")
        return self


class Skill(Record):
    id: Identifier
    stages: tuple[Stage, ...]
    text: str
    sha256: str


class Task(Record):
    id: Identifier
    split: Literal["discovery", "holdout"]
    instruction: str
    starter: str
    # Only the grader hash enters the plan; grader text never enters model messages.
    grader_sha256: str
    sha256: str


class Experiment(Record):
    name: str
    model: str
    skills: tuple[Skill, ...]
    tasks: tuple[Task, ...]
    sha256: str


class Condition(Record):
    id: str
    policy: Literal["global", "scoped"]
    skill_ids: tuple[str, ...]
    control: Literal["none", "neutral-a", "neutral-b"] = "none"


class PlannedRun(Record):
    id: str
    task_id: str
    condition_id: str
    repeat: int
