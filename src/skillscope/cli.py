"""Offline preparation commands and explicitly requested bounded model runs."""

import io
import json
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from skillscope.loader import load_experiment
from skillscope.models import Stage
from skillscope.planner import build_plan, conditions_for
from skillscope.prompts import build_messages

app = typer.Typer(help="SkillScope：技能实验准备、阶段运行与独立评分。", no_args_is_help=True)
ConfigOption = Annotated[Path, typer.Option("--config", "-c", help="实验配置 JSON 文件")]


def main() -> None:
    """Use UTF-8 for Chinese CLI output, including pipes on English Windows hosts."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    app()


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
    typer.echo(f"模型配置：{experiment.model}（check 只检查本地材料，不连接模型）")
    typer.echo(f"输入指纹：{experiment.sha256}")


@app.command()
def plan(
    config: ConfigOption = Path("examples/experiment.json"),
    repeats: Annotated[int, typer.Option(min=1)] = 3,
    seed: int = 42,
    split: Split = Split.DISCOVERY,
    max_runs: Annotated[int, typer.Option(min=1)] = 1000,
    controls: bool = False,
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("results/plan.json"),
) -> None:
    """生成实验排期，不执行实验；拒绝覆盖已有文件。"""
    try:
        experiment = load_experiment(config)
        payload = build_plan(experiment, repeats, seed, split.value, max_runs, controls)
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
        selected = next(
            (item for item in conditions_for(experiment, controls=True) if item.id == condition),
            None,
        )
        if selected is None:
            choices = ", ".join(item.id for item in conditions_for(experiment, controls=True))
            raise ValueError(f"unknown condition: {condition}; choose: {choices}")
        messages = build_messages(experiment, task, selected, stage)
    except (ValueError, OSError) as error:
        fail(error)
    typer.echo(json.dumps(messages, ensure_ascii=False, indent=2))


@app.command("sandbox-build")
def sandbox_build(docker: Annotated[str | None, typer.Option()] = None) -> None:
    """构建评分镜像，不调用模型。首次需要下载基础镜像。"""
    from skillscope.sandbox import SandboxError, build_image, preflight
    from skillscope.settings import find_docker

    try:
        executable = find_docker(docker)
        build_image(executable)
        typer.echo(f"评分镜像已就绪：{preflight(executable)}")
    except (ValueError, OSError, TimeoutError, SandboxError) as error:
        fail(error)


@app.command("run")
def run(
    config: ConfigOption = Path("examples/experiment.json"),
    task: str = "clamp",
    condition: str = "baseline",
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("results/first-run"),
    env_file: Path = Path(".env"),
    docker: Annotated[str | None, typer.Option()] = None,
    max_calls: Annotated[int, typer.Option(min=1, max=3)] = 3,
    max_tokens: Annotated[int, typer.Option(min=128, max=4096)] = 1024,
    timeout: Annotated[float, typer.Option(min=1, max=120)] = 45,
    allow_holdout: bool = False,
) -> None:
    """真实运行一道题：调查→修改→检查→独立评分；会消耗模型 API 额度。"""
    from skillscope.runner import run_task
    from skillscope.sandbox import SandboxError
    from skillscope.settings import load_settings

    try:
        settings = load_settings(env_file, docker)
        result = run_task(
            config, task, condition, settings, output, max_calls, max_tokens, timeout, allow_holdout
        )
    except (ValueError, OSError, TimeoutError, SandboxError) as error:
        fail(error)
    typer.echo(f"运行状态：{result['status']}；记录：{output / 'run.json'}")
    typer.echo(
        f"实际尝试 {result['calls_attempted']} 次模型调用；token：{result['reported_tokens']}"
    )
    if result["grading"]:
        typer.echo(f"独立评分：{result['grading']}")
    if result["status"] != "passed":
        raise typer.Exit(code=1)


@app.command("corpus-check")
def corpus_check(
    config: ConfigOption = Path("benchmarks/stage3/experiment.json"),
    output: Path = Path("results/stage3-corpus-check"),
    docker: Annotated[str | None, typer.Option()] = None,
) -> None:
    """用参考实现和缺陷初始实现检查全部题目的评分器，不调用模型。"""
    from skillscope.corpus import check_corpus
    from skillscope.sandbox import SandboxError
    from skillscope.settings import find_docker

    try:
        result = check_corpus(config, find_docker(docker), output)
    except (ValueError, OSError, SandboxError) as error:
        fail(error)
    typer.echo(f"评分器校验通过：{result['passed']}；模型调用：0")
    if not result["passed"]:
        raise typer.Exit(code=1)


@app.command("batch")
def batch(
    config: ConfigOption = Path("benchmarks/stage3/experiment.json"),
    output: Path = Path("results/stage3-batch"),
    env_file: Path = Path(".env"),
    docker: Annotated[str | None, typer.Option()] = None,
    repeats: Annotated[int, typer.Option(min=2)] = 3,
    seed: int = 731,
    workers: Annotated[int, typer.Option(min=1, max=4)] = 3,
    max_calls: Annotated[int, typer.Option(min=3)] = 444,
    max_total_tokens: Annotated[int, typer.Option(min=1)] = 1_000_000,
    max_usd: Annotated[float, typer.Option(min=0.000001)] = 1.0,
    max_output_tokens: Annotated[int, typer.Option(min=128, max=4096)] = 1024,
    resume: bool = False,
) -> None:
    """运行冻结的基线预检和随机排期重复实验，会消耗 API 额度；不自动重试。"""
    from skillscope.batch import Limits, run_batch
    from skillscope.report import save_report
    from skillscope.sandbox import SandboxError
    from skillscope.settings import load_settings

    try:
        settings = load_settings(env_file, docker)
        limits = Limits(max_calls, max_total_tokens, max_usd, max_output_tokens, workers)
        result = run_batch(config, settings, output, limits, repeats, seed, resume)
        save_report(output)
    except (ValueError, OSError, SandboxError) as error:
        fail(error)
    typer.echo(f"批次状态：{result['status']}；完成 {result['completed']}/{result['planned']}")
    typer.echo(f"报告：{output / 'report.md'}")
    if result["status"] != "completed":
        raise typer.Exit(code=1)


@app.command("report")
def report(batch_dir: Annotated[Path, typer.Argument()]) -> None:
    """从已有本地记录重新生成统计报告，不调用模型。"""
    from skillscope.report import save_report

    try:
        result = save_report(batch_dir)
    except (ValueError, OSError, KeyError) as error:
        fail(error)
    typer.echo(f"报告已生成：{batch_dir / 'report.md'}；结论：{result['conclusion']}")
