import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion

from scripts import repo_agent
from skillscope.settings import Settings

TASK = Path(__file__).resolve().parents[1] / "benchmarks/repo-prototype/cart/task.json"


def response(calls):
    return ChatCompletion.model_validate(
        {
            "id": "test",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": f"call{index}",
                                "type": "function",
                                "function": {
                                    "name": name,
                                    "arguments": arguments
                                    if isinstance(arguments, str)
                                    else json.dumps(arguments),
                                },
                            }
                            for index, (name, arguments) in enumerate(calls)
                        ],
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
        }
    )


@pytest.fixture
def fake_agent(monkeypatch):
    requests, grades, sequence = [], [], []
    monkeypatch.setattr(repo_agent, "preflight", lambda _: "test-image")

    def grade(workspace, docker, image, output, hidden=False):
        output.mkdir(parents=True)
        grades.append(hidden)
        fixed = workspace.fingerprint() != workspace.initial_fingerprint
        return {
            "status": "passed" if fixed else "failed",
            "tests": 19 if hidden else 2,
            "failures": 0 if fixed else 1,
        }

    monkeypatch.setattr(repo_agent, "grade_workspace", grade)

    class Backend:
        def __init__(self, *args):
            self.client = SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))
            )

        def create(self, **kwargs):
            requests.append(copy.deepcopy(kwargs))
            return response(sequence.pop(0))

        def close(self):
            pass

        def redact(self, value):
            return json.loads(json.dumps(value).replace("test-secret", "[REDACTED]"))

    monkeypatch.setattr(repo_agent, "DeepSeekBackend", Backend)
    return requests, grades, sequence


def finish(text="Short phase summary."):
    return [("finish_phase", {"summary": text})]


def test_agent_reads_patches_tests_and_keeps_hidden_grader_out_of_messages(tmp_path, fake_agent):
    requests, grades, sequence = fake_agent
    changes = {
        path: (TASK.parent / "reference" / path).read_text(encoding="utf-8")
        for path in ("shop/money.py", "shop/cart.py")
    }
    sequence.extend(
        [
            [("read_file", {"path": "shop/cart.py"}), ("read_file", {"path": "shop/money.py"})],
            finish(),
            [("write_file", {"path": path, "content": text}) for path, text in changes.items()],
            [("run_public_tests", {})],
            finish(),
            finish(),
        ]
    )
    result = repo_agent.run_agent(TASK, Settings(api_key="test-secret"), tmp_path / "run")
    assert result["status"] == "passed" and result["calls_attempted"] == 6
    assert result["usage_complete"] and result["reported_tokens"]["total_tokens"] == 120
    assert grades == [False, False, True]
    assert result["public_test_runs_by_model"] == 1
    hidden = (TASK.parent / "hidden_tests.py").read_text(encoding="utf-8")
    assert hidden not in json.dumps(requests)
    assert "4 model requests are available in this phase." in requests[0]["messages"][0]["content"]
    phase_starts = [request for request in requests if len(request["messages"]) == 2]
    assert len(phase_starts) == 3  # New input history per phase.
    assert all(request["extra_body"]["thinking"]["type"] == "disabled" for request in requests)
    assert "test-secret" not in (tmp_path / "run/trace.jsonl").read_text()
    assert json.loads((tmp_path / "run/workspace-final.json").read_text()) == {
        **changes,
        "shop/__init__.py": (TASK.parent / "project/shop/__init__.py").read_text(),
    }


def test_readonly_phase_rejects_writes_and_retains_failed_candidate(tmp_path, fake_agent):
    _, grades, sequence = fake_agent
    sequence.extend(
        [[("write_file", {"path": "shop/cart.py", "content": "bad"})], finish(), finish(), finish()]
    )
    result = repo_agent.run_agent(TASK, Settings(api_key="test-secret"), tmp_path / "run")
    assert result["status"] == "failed"
    assert grades == [False, True]
    events = [json.loads(line) for line in (tmp_path / "run/trace.jsonl").read_text().splitlines()]
    tool = next(event for event in events if event["type"] == "tool_result")
    assert tool["result"]["ok"] is False


def test_scoped_guides_enter_only_declared_phases_and_do_not_change_tool_permissions(
    tmp_path, fake_agent
):
    from skillscope.loader import digest
    from skillscope.models import Condition, Skill, Stage

    requests, _, sequence = fake_agent
    sequence.extend([finish(), finish(), finish()])
    skills = (
        Skill(
            id="patch-guide",
            text="Use a minimal repair.",
            stages=(Stage.IMPLEMENT,),
            sha256=digest("Use a minimal repair."),
        ),
    )
    condition = Condition(id="scoped", policy="scoped", skill_ids=("patch-guide",))
    result = repo_agent.run_agent(
        TASK, Settings(api_key="test-secret"), tmp_path / "run", skills=skills, condition=condition
    )
    assert result["condition"] == "scoped"
    assert "Use a minimal repair." not in requests[0]["messages"][0]["content"]
    assert "Use a minimal repair." in requests[1]["messages"][0]["content"]
    assert "Use a minimal repair." not in requests[2]["messages"][0]["content"]
    assert "write_file" not in {tool["function"]["name"] for tool in requests[2]["tools"]}


def test_controller_transitions_without_model_finish_or_additional_requests(tmp_path, fake_agent):
    requests, grades, sequence = fake_agent
    sequence.extend([[("list_files", {})]] * 10)
    result = repo_agent.run_agent(TASK, Settings(api_key="test-secret"), tmp_path / "run")
    assert result["status"] == "failed"  # Trusted final grader still rejects untouched code.
    assert result["calls_attempted"] == len(requests) == 10
    assert grades == [False, True]
    events = [json.loads(line) for line in (tmp_path / "run/trace.jsonl").read_text().splitlines()]
    transitions = [event for event in events if event["type"] == "phase_budget_transition"]
    assert [event["stage"] for event in transitions] == ["investigate", "implement", "verify"]
    assert all(event["summary_origin"] == "observed_tool_log" for event in transitions)
    assert all("No model reasoning summary" in event["summary"] for event in transitions)
    assert all(len(event["summary"]) <= 2000 for event in transitions)


def test_controller_reserves_verification_within_global_budget(tmp_path, fake_agent):
    requests, grades, sequence = fake_agent
    changes = {
        path: (TASK.parent / "reference" / path).read_text(encoding="utf-8")
        for path in ("shop/money.py", "shop/cart.py")
    }
    sequence.extend(
        [
            *([[("list_files", {})]] * 3),
            finish(),
            [("read_file", {"path": "shop/money.py"})],
            [("write_file", {"path": path, "content": text}) for path, text in changes.items()],
            [("run_public_tests", {})],
            finish(),
            [("run_public_tests", {})],
            finish(),
        ]
    )
    result = repo_agent.run_agent(TASK, Settings(api_key="test-secret"), tmp_path / "run")
    assert result["status"] == "passed" and result["calls_attempted"] == 10
    assert grades == [False, False, False, True]
    assert all(request["tool_choice"] == "required" for request in requests)
    for request in (requests[0], requests[-1]):
        assert "write_file" not in {tool["function"]["name"] for tool in request["tools"]}


def test_reduced_eight_request_budget_keeps_all_three_phases(tmp_path, fake_agent):
    requests, grades, sequence = fake_agent
    sequence.extend(
        [
            [("list_files", {})],
            [("read_file", {"path": "shop/money.py"})],
            finish(),
            [("write_file", {"path": "shop/money.py", "content": "def amount(text): return 0\n"})],
            [("run_public_tests", {})],
            finish(),
            [("run_public_tests", {})],
            finish(),
        ]
    )
    result = repo_agent.run_agent(
        TASK,
        Settings(api_key="test-secret"),
        tmp_path / "run",
        max_requests=8,
        per_phase_requests=3,
    )
    assert result["status"] == "passed" and result["calls_attempted"] == 8
    assert result["budget"]["max_requests"] == 8
    assert result["budget"]["per_phase_requests"] == 3
    assert len(requests) == 8 and grades[-1] is True


def test_automatic_handoff_records_actual_edits_and_tests_without_invented_analysis(
    tmp_path, fake_agent
):
    requests, _, sequence = fake_agent
    sequence.extend(
        [
            [("read_file", {"path": "shop/money.py"})],
            [("read_file", {"path": "public_tests.py"})],
            [("list_files", [])],  # Malformed argument shape is logged, not executed.
            [("write_file", {"path": "shop/money.py", "content": "def amount(text): return 0\n"})],
            [("run_public_tests", {})],
            [("list_files", {})],
            [("list_files", {})],
            [("list_files", {})],
        ]
    )
    result = repo_agent.run_agent(
        TASK,
        Settings(api_key="test-secret"),
        tmp_path / "run",
        max_requests=8,
        per_phase_requests=3,
    )
    assert result["status"] == "passed" and result["calls_attempted"] == 8
    assert "shop/money.py" in requests[3]["messages"][1]["content"]
    verify = json.loads(requests[6]["messages"][1]["content"])["handoff"]
    assert "write_file" in verify and '"status": "passed"' in verify
    assert "No model reasoning summary" in verify


def test_invalid_phase_finish_is_recorded_as_model_output_failure(tmp_path, fake_agent):
    _, grades, sequence = fake_agent
    sequence.extend([finish("x" * 2001)])
    result = repo_agent.run_agent(TASK, Settings(api_key="test-secret"), tmp_path / "run")
    assert result["status"] == "invalid_output"
    assert result["calls_attempted"] == 1 and result["usage_complete"]
    assert grades == [False]


def test_legitimate_parallel_inventory_reads_do_not_trip_a_request_count_limit(
    tmp_path, fake_agent
):
    requests, _, sequence = fake_agent
    reads = [("list_files", {})] + [
        ("read_file", {"path": path})
        for path in (
            "shop/cart.py",
            "shop/money.py",
            "public_tests.py",
            "README.md",
            "shop/__init__.py",
        )
    ]
    assert len(reads) == 6
    changes = {
        path: (TASK.parent / "reference" / path).read_text(encoding="utf-8")
        for path in ("shop/money.py", "shop/cart.py")
    }
    sequence.extend(
        [
            reads,
            finish(),
            [("write_file", {"path": path, "content": text}) for path, text in changes.items()],
            [("run_public_tests", {})],
            finish(),
            finish(),
        ]
    )
    result = repo_agent.run_agent(TASK, Settings(api_key="test-secret"), tmp_path / "run")
    assert result["status"] == "passed" and len(requests) == 6
    assert result["budget"]["max_tools_per_response"] == 18


def test_invalid_json_tool_arguments_get_bounded_feedback_and_can_be_corrected(
    tmp_path, fake_agent
):
    requests, _, sequence = fake_agent
    changes = {
        path: (TASK.parent / "reference" / path).read_text(encoding="utf-8")
        for path in ("shop/money.py", "shop/cart.py")
    }
    sequence.extend(
        [
            [("read_file", {"path": "shop/cart.py"})],
            finish(),
            [("write_file", '{"path":')],
            [("write_file", {"path": path, "content": text}) for path, text in changes.items()],
            [("run_public_tests", {})],
            finish(),
            finish(),
        ]
    )
    output = tmp_path / "run"
    result = repo_agent.run_agent(TASK, Settings(api_key="test-secret"), output)
    assert result["status"] == "passed" and len(requests) == 7
    events = [json.loads(line) for line in (output / "trace.jsonl").read_text().splitlines()]
    rejected = [
        event for event in events if event["type"] == "tool_result" and not event["result"]["ok"]
    ]
    assert len(rejected) == 1 and rejected[0]["raw_arguments"] == '{"path":'
    read_results = [
        message["content"]
        for request in requests
        for message in request["messages"]
        if message["role"] == "tool" and message["content"].startswith("File:")
    ]
    assert any("def checkout(lines, discount_bps):\n" in text for text in read_results)
