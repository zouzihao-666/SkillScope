"""Offline CLI. No command in this milestone makes a model API request."""

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from skillscope.loader import load_experiment
from skillscope.models import Stage
from skillscope.planner import build_plan, conditions_for
from skillscope.prompts import build_messages

app = typer.Typer(
    help="SkillScope：实验准备与阶段指令预览（当前不调用模型）。", no_args_is_help=True
)
ConfigOption = Annotated[Path, typer.Option("--config", "-c", help="实验配置 JSON 文件")]


class Split(StrEnum):
    DISCOVERY = "discovery"
    HOLDOUT = "holdout"


def fail(error: Exception) -> None:
    typer.echo(f"错误：{error}", err=True)
    raise typer.Exit(code=1)


@app.command()
def check(config: ConfigOption = Path("examples/experiment.json")) -> None:
    """检查任务、技能、独立评分文件和配置格式。"""
    try:
        experiment = load_experiment(config)
    except (ValueError, OSError) as error:
        fail(error)
    typer.echo(f"配置有效：{experiment.name}")
    typer.echo(f"技能：{len(experiment.skills)}；任务：{len(experiment.tasks)}")
    for split in Split:
        typer.echo(
            f"  {split.value}: {sum(task.split == split.value for task in experiment.tasks)}"
        )
    typer.echo(f"模型配置：{experiment.model}（尚未连接）")
    typer.echo(f"输入指纹：{experiment.sha256}")


@app.command()
def plan(
    config: ConfigOption = Path("examples/experiment.json"),
    repeats: Annotated[int, typer.Option(min=1)] = 3,
    seed: int = 42,
    split: Split = Split.DISCOVERY,
    max_runs: Annotated[int, typer.Option(min=1)] = 1000,
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("results/plan.json"),
) -> None:
    """生成实验排期，不执行实验；拒绝覆盖已有文件。"""
    try:
        experiment = load_experiment(config)
        payload = build_plan(experiment, repeats, seed, split.value, max_runs)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
    except (ValueError, OSError) as error:
        fail(error)
    typer.echo(f"已生成计划：{output}")
    typer.echo(f"{payload['run_count']} 次计划运行；每次设调查、修改、验证三个阶段。")
    typer.echo("状态：planned_not_executed；没有模型调用、评分或实验结论。")


@app.command("preview")
def preview(
    config: ConfigOption = Path("examples/experiment.json"),
    task: str = "clamp",
    condition: str = "scoped",
    stage: Stage = Stage.INVESTIGATE,
) -> None:
    """查看某个任务在指定分组和阶段会收到的消息。"""
    try:
        experiment = load_experiment(config)
        selected = next((item for item in conditions_for(experiment) if item.id == condition), None)
        if selected is None:
            choices = ", ".join(item.id for item in conditions_for(experiment))
            raise ValueError(f"unknown condition: {condition}; choose: {choices}")
        messages = build_messages(experiment, task, selected, stage)
    except (ValueError, OSError) as error:
        fail(error)
    typer.echo(json.dumps(messages, ensure_ascii=False, indent=2))
