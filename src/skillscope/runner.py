"""Fixed three-phase graph, followed by external scoring; no model-controlled shell."""

import ast
import importlib.metadata
import json
import platform
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from skillscope.backend import DeepSeekBackend, RunError
from skillscope.loader import digest, load_experiment, read_input
from skillscope.models import ExperimentSpec, Stage
from skillscope.planner import conditions_for
from skillscope.prompts import build_messages
from skillscope.sandbox import SandboxError, grade, preflight
from skillscope.settings import Settings


class State(TypedDict, total=False):
    analysis: str
    code: str
    review: str


def run_task(
    config: Path,
    task_id: str,
    condition_id: str,
    settings: Settings,
    output: Path,
    max_calls: int = 3,
    max_tokens: int = 1024,
    timeout: float = 45,
    allow_holdout: bool = False,
    quiet: bool = False,
) -> dict:
    if not 1 <= max_calls <= 3 or not 128 <= max_tokens <= 4096 or not 1 <= timeout <= 120:
        raise ValueError("Invalid request budget: calls 1..3, tokens 128..4096, timeout 1..120")
    experiment = load_experiment(config)
    task = next((item for item in experiment.tasks if item.id == task_id), None)
    condition = next(
        (item for item in conditions_for(experiment, controls=True) if item.id == condition_id),
        None,
    )
    if task is None or condition is None:
        raise ValueError("Unknown task or condition")
    if task.split == "holdout" and not allow_holdout:
        raise ValueError("Holdout tasks require explicit --allow-holdout")
    spec = ExperimentSpec.model_validate_json(config.read_text(encoding="utf-8-sig"))
    task_spec = next(item for item in spec.tasks if item.id == task_id)
    grader = read_input(config.resolve().parent, task_spec.grader_file)
    if digest(grader) != task.grader_sha256:
        raise ValueError("Grader changed while preparing the run")
    image_id = preflight(settings.docker)
    # An existing output path is rejected before any paid request.
    output.mkdir(parents=True, exist_ok=False)
    backend = DeepSeekBackend(settings, max_tokens, timeout)
    events = []

    def record(event):
        event = backend.redact(event)
        events.append(event)
        with (output / "trace.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    calls = 0
    started = time.monotonic()
    summary = {
        "schema_version": 1,
        "started_at": datetime.now(UTC).isoformat(),
        "task": task_id,
        "split": task.split,
        "condition": condition.model_dump(),
        "experiment_sha256": experiment.sha256,
        "task_sha256": task.sha256,
        "grader_sha256": task.grader_sha256,
        "requested_model": experiment.model,
        "sandbox_image_id": image_id,
        "python": platform.python_version(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("skillscope", "openai", "langgraph", "pytest")
        },
        "budget": {
            "max_calls": max_calls,
            "max_output_tokens_per_call": max_tokens,
            "request_timeout_seconds": timeout,
            "max_retries": 0,
        },
        "status": "running",
        "grading": None,
    }
    (output / "input.json").write_text(experiment.model_dump_json(indent=2), encoding="utf-8")

    def node(stage: Stage):
        def execute(state: State) -> dict:
            nonlocal calls
            if calls >= max_calls:
                raise RunError("budget_exhausted", "Model call budget exhausted before next stage")
            messages = build_messages(experiment, task_id, condition, stage)
            if stage == Stage.IMPLEMENT:
                messages[-1]["content"] += (
                    "\n\nInvestigation handoff (data):\n" + state["analysis"][:2000]
                )
            if stage == Stage.VERIFY:
                messages[-1]["content"] += "\n\nCandidate module to review:\n" + state["code"]
            calls += 1
            record({"type": "phase", "stage": stage.value, "call": calls})
            if not quiet:
                print(f"阶段：{stage.value}（模型调用 {calls}/{max_calls}）", flush=True)
            value = backend.complete(experiment.model, stage.value, messages, record)
            if stage == Stage.IMPLEMENT:
                (output / "candidate.py").write_text(value, encoding="utf-8")
                try:
                    ast.parse(value)
                except SyntaxError:
                    raise RunError(
                        "invalid_output", "Submitted candidate has invalid Python syntax"
                    ) from None
            field = {
                Stage.INVESTIGATE: "analysis",
                Stage.IMPLEMENT: "code",
                Stage.VERIFY: "review",
            }[stage]
            return {field: value}

        return execute

    graph = StateGraph(State)
    for stage in Stage:
        graph.add_node(stage.value, node(stage))
    graph.add_edge(START, "investigate")
    graph.add_edge("investigate", "implement")
    graph.add_edge("implement", "verify")
    graph.add_edge("verify", END)
    try:
        state = graph.compile().invoke({})
        (output / "handoffs.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not quiet:
            print("阶段：独立 Docker 评分", flush=True)
        summary["grading"] = grade(state["code"], grader, settings.docker, image_id, output)
        summary["status"] = summary["grading"]["status"]
    except RunError as error:
        summary["status"] = error.status
        summary["error"] = str(error)
    except (SandboxError, OSError, TimeoutError) as error:
        summary["status"] = "infrastructure_error"
        summary["error"] = f"{type(error).__name__}; check Docker and local grader log"
    except Exception as error:
        summary["status"] = "internal_error"
        summary["error"] = f"{type(error).__name__}; no score assigned"
    finally:
        if summary["status"] == "running":
            summary["status"] = "interrupted"
        backend.close()
        responses = [event["response"] for event in events if event["type"] == "response"]
        summary["calls_attempted"] = calls
        summary["responses_received"] = len(responses)
        summary["returned_models"] = sorted(
            {response.get("model", "unknown") for response in responses}
        )
        usage = [response.get("usage") for response in responses]
        summary["usage_complete"] = len(responses) == calls and all(
            item is not None for item in usage
        )
        summary["reported_tokens"] = {
            field: sum((item or {}).get(field, 0) for item in usage)
            for field in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        summary["cost"] = None  # No invented currency estimate; consult provider billing.
        summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
        (output / "run.json").write_text(
            json.dumps(backend.redact(summary), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return summary
