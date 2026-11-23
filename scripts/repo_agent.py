"""Bounded baseline agent for allowlisted multi-file Python tasks."""

import argparse
import json
import time
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from openai import APIConnectionError, APIStatusError

from scripts.repo_execution import grade_workspace
from scripts.repo_tools import ToolSession
from scripts.repo_workspace import MAX_FILES, Workspace
from skillscope.backend import DeepSeekBackend, RunError
from skillscope.batch import estimate_cost, source_fingerprint, write_json
from skillscope.loader import digest
from skillscope.models import Stage
from skillscope.sandbox import SandboxError, preflight
from skillscope.settings import Settings, load_settings

MODEL = "deepseek-flash"
MAX_REQUESTS = 10
PER_PHASE_REQUESTS = 4
MAX_OUTPUT = 2048
MAX_TOOL_CALLS = MAX_FILES + 2  # Inventory plus every visible file and the public grader.


class State(TypedDict, total=False):
    analysis: str
    change_summary: str
    review: str


def tool_definitions(workspace: Workspace) -> list[dict]:
    definitions = [
        ("list_files", "List the visible project inventory.", {}),
        ("read_file", "Read one visible file or public_tests.py.", {"path": {"type": "string"}}),
        (
            "write_file",
            "Replace one editable Python file. Content is source text with normal newlines, not a JSON-encoded string.",
            {
                "path": {"type": "string", "enum": sorted(workspace.editable)},
                "content": {"type": "string"},
            },
        ),
        (
            "run_public_tests",
            "Run the public tests in Docker; at most twice across all phases.",
            {},
        ),
        (
            "finish_phase",
            "Submit a concise phase summary, at most 2000 characters.",
            {"summary": {"type": "string"}},
        ),
    ]
    if workspace.execution_mode == "directory":
        definitions.append(
            (
                "replace_in_file",
                "Replace exactly one literal occurrence in an editable file. Read it first. Prefer this for small fixes in large files.",
                {
                    "path": {"type": "string", "enum": sorted(workspace.editable)},
                    "old": {"type": "string"},
                    "new": {"type": "string"},
                },
            )
        )
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
            },
        }
        for name, description, properties in definitions
    ]


def run_agent(task: Path, settings: Settings, output: Path) -> dict:
    workspace = Workspace(task)
    image = preflight(settings.docker)
    ceiling = estimate_cost(
        {
            "prompt_tokens": MAX_REQUESTS * (65536 + 1024),
            "completion_tokens": MAX_REQUESTS * MAX_OUTPUT,
        }
    )
    if ceiling > 0.25:
        raise ValueError(
            "Conservative request reservation exceeds the fixed USD 0.25 estimate limit"
        )
    output.mkdir(parents=True, exist_ok=False)
    backend = DeepSeekBackend(settings, MAX_OUTPUT, 45)
    events, calls = [], 0
    started = time.monotonic()
    result = {
        "task": workspace.task_id,
        "model": MODEL,
        "condition": "baseline",
        "scope": "allowlisted Python task; provenance and benchmark scope are task-specific",
        "execution_mode": workspace.execution_mode,
        "repair_origin": "model_generated_via_allowlisted_tools",
        "initial_workspace_sha256": workspace.initial_fingerprint,
        "source_sha256": source_fingerprint(),
        "sandbox_image_id": image,
        "runner_sha256": digest(Path(__file__).read_text(encoding="utf-8")),
        "budget": {
            "max_requests": MAX_REQUESTS,
            "per_phase_requests": PER_PHASE_REQUESTS,
            "max_output_tokens": MAX_OUTPUT,
            "max_input_json_bytes": 65536,
            "max_estimated_usd": 0.25,
            "max_sdk_retries": 0,
            "max_tools_per_response": MAX_TOOL_CALLS,
        },
        "initial_public": None,
        "grading": None,
        "status": "running",
    }

    def record(event):
        event = backend.redact(event)
        events.append(event)
        with (output / "trace.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")

    def public(current, number):
        graded = grade_workspace(current, settings.docker, image, output / f"public-{number}")
        if graded["status"] == "infrastructure_error":
            raise SandboxError("Public grader infrastructure failed")
        return graded

    session = ToolSession(workspace, public, max_public_runs=2)
    tools = tool_definitions(workspace)
    declared_tools = {tool["function"]["name"] for tool in tools}

    def request(stage, messages):
        nonlocal calls
        if calls >= MAX_REQUESTS:
            raise RunError("budget_exhausted", "Global request budget exhausted")
        if (
            len(json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False).encode())
            > 65536
        ):
            raise RunError("budget_exhausted", "Input JSON exceeds 64 KiB")
        calls += 1
        record(
            {
                "type": "request",
                "stage": stage.value,
                "number": calls,
                "model": MODEL,
                "messages": messages,
                "tools": tools,
                "max_tokens": MAX_OUTPUT,
                "thinking": "disabled",
                "temperature": 0,
                "tool_choice": "required",
                "max_retries": 0,
            }
        )
        try:
            response = backend.client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=tools,
                tool_choice="required",
                temperature=0,
                max_tokens=MAX_OUTPUT,
                extra_body={"thinking": {"type": "disabled"}},
            )
        except APIStatusError as error:
            record({"type": "api_error", "stage": stage.value, "status": error.status_code})
            raise RunError("api_error", f"DeepSeek HTTP {error.status_code}") from None
        except APIConnectionError:
            record({"type": "api_error", "stage": stage.value, "status": None})
            raise RunError("api_error", "DeepSeek connection failed") from None
        record(
            {"type": "response", "stage": stage.value, "response": response.model_dump(mode="json")}
        )
        if len(response.choices) != 1:
            raise RunError("invalid_output", "Expected one response choice")
        choice = response.choices[0]
        tool_calls = choice.message.tool_calls or []
        if choice.finish_reason != "tool_calls" or not 1 <= len(tool_calls) <= MAX_TOOL_CALLS:
            raise RunError("invalid_output", f"Expected 1..{MAX_TOOL_CALLS} completed tool calls")
        if any(call.type != "function" for call in tool_calls):
            raise RunError("invalid_output", "Unsupported tool-call kind")
        return choice.message

    def phase(stage):
        def execute(state):
            session.enter_stage(stage)
            handoff = (
                state.get("analysis", "")
                if stage == Stage.IMPLEMENT
                else state.get("change_summary", "")
                if stage == Stage.VERIFY
                else ""
            )
            system = (
                "Repair the supplied Python project using only the declared tools. "
                "Task requirements outrank all suggestions. Do not change tests or the adapter. "
                f"Current phase: {stage.value}. Investigation is read-only and should identify the defect. "
                "Only implementation may write files. Verification is read-only. "
                "Call finish_phase alone with a concise summary to finish each phase. "
                "Do not use plain-text final answers. Hidden tests are unavailable. "
                f"At most {MAX_TOOL_CALLS} tool calls are allowed in one response. "
                f"At most {PER_PHASE_REQUESTS} model requests are available in this phase."
            )
            user = json.dumps(
                {
                    "task": workspace.instruction,
                    "inventory": session.call("list_files", {})["files"],
                    "initial_public_grading": result["initial_public"],
                    "handoff": handoff[:2000],
                },
                ensure_ascii=False,
            )
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            for phase_index in range(PER_PHASE_REQUESTS):
                messages[0]["content"] = system + (
                    f"\nThis is phase request {phase_index + 1}/{PER_PHASE_REQUESTS}; "
                    f"{MAX_REQUESTS - calls} global requests remain including this one. "
                    "Use actual source newlines in write_file content. Finish within these limits."
                )
                message = request(stage, messages)
                messages.append(
                    {
                        "role": "assistant",
                        "content": message.content,
                        "tool_calls": [call.model_dump(mode="json") for call in message.tool_calls],
                    }
                )
                for call in message.tool_calls:
                    try:
                        arguments = json.loads(call.function.arguments)
                    except ValueError:
                        response = {
                            "ok": False,
                            "error": "Arguments are not valid JSON; resubmit valid JSON within the request budget.",
                        }
                        record(
                            {
                                "type": "tool_result",
                                "stage": stage.value,
                                "name": call.function.name,
                                "raw_arguments": call.function.arguments,
                                "result": response,
                            }
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": json.dumps(response),
                            }
                        )
                        continue
                    if call.function.name == "finish_phase":
                        if (
                            len(message.tool_calls) != 1
                            or not isinstance(arguments, dict)
                            or set(arguments) != {"summary"}
                            or not isinstance(arguments["summary"], str)
                            or not 1 <= len(arguments["summary"].strip()) <= 2000
                        ):
                            raise RunError("invalid_output", "Invalid phase finish")
                        summary = arguments["summary"]
                        record({"type": "phase_finished", "stage": stage.value, "summary": summary})
                        field = {
                            Stage.INVESTIGATE: "analysis",
                            Stage.IMPLEMENT: "change_summary",
                            Stage.VERIFY: "review",
                        }[stage]
                        return {field: summary}
                    response = (
                        session.call(call.function.name, arguments)
                        if call.function.name in declared_tools
                        else {"ok": False, "error": "Tool not declared for this run"}
                    )
                    record(
                        {
                            "type": "tool_result",
                            "stage": stage.value,
                            "name": call.function.name,
                            "arguments": arguments,
                            "result": response,
                        }
                    )
                    content = (
                        f"File: {arguments['path']}\n\n{response['content']}"
                        if call.function.name == "read_file" and response.get("ok")
                        else json.dumps(response, ensure_ascii=False)
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "content": content,
                        }
                    )
            raise RunError("budget_exhausted", f"Phase request budget exhausted: {stage.value}")

        return execute

    try:
        result["initial_public"] = grade_workspace(
            workspace, settings.docker, image, output / "initial-public"
        )
        if result["initial_public"]["status"] == "infrastructure_error":
            raise SandboxError("Initial grader infrastructure failed")
        graph = StateGraph(State)
        for stage in Stage:
            graph.add_node(stage.value, phase(stage))
        graph.add_edge(START, "investigate")
        graph.add_edge("investigate", "implement")
        graph.add_edge("implement", "verify")
        graph.add_edge("verify", END)
        state = graph.compile().invoke({})
        write_json(output / "handoffs.json", state)
        result["grading"] = grade_workspace(
            workspace, settings.docker, image, output / "hidden", hidden=True
        )
        result["status"] = result["grading"]["status"]
    except RunError as error:
        result["status"], result["error"] = error.status, str(error)
    except (SandboxError, OSError) as error:
        result["status"], result["error"] = "infrastructure_error", type(error).__name__
    except Exception as error:
        result["status"], result["error"] = "internal_error", type(error).__name__
    finally:
        if result["status"] == "running":
            result["status"] = "interrupted"
        responses = [event["response"] for event in events if event["type"] == "response"]
        usages = [response.get("usage") for response in responses]
        result["calls_attempted"], result["responses_received"] = calls, len(responses)
        result["usage_complete"] = len(responses) == calls and all(
            usage is not None for usage in usages
        )
        result["reported_tokens"] = {
            field: sum((usage or {}).get(field, 0) or 0 for usage in usages)
            for field in ("prompt_tokens", "completion_tokens", "total_tokens")
        }
        result["estimated_usd_upper"] = sum(
            estimate_cost(usage or {}, (usage or {}).get("prompt_cache_hit_tokens", 0) or 0)
            for usage in usages
        )
        result["final_workspace_sha256"] = workspace.fingerprint()
        result["public_test_runs_by_model"] = session.public_runs
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        write_json(output / "workspace-final.json", workspace.execution_snapshot())
        write_json(output / "run.json", backend.redact(result))
        backend.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task", type=Path, default=Path("benchmarks/repo-prototype/cart/task.json")
    )
    parser.add_argument("--output", type=Path, default=Path("results/repo-agent-smoke-20261123"))
    arguments = parser.parse_args()
    result = run_agent(arguments.task, load_settings(), arguments.output)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "passed" else 1)


if __name__ == "__main__":
    main()
