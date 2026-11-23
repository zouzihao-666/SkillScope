from pathlib import Path

from scripts.repo_tools import ToolSession
from scripts.repo_workspace import Workspace
from skillscope.models import Stage

FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks/repo-prototype/cart/task.json"


def test_public_tests_are_readable_but_hidden_tests_and_arbitrary_tools_are_not():
    session = ToolSession(Workspace(FIXTURE), lambda *_: {})
    assert session.call("read_file", {"path": "public_tests.py"})["ok"]
    assert not session.call("read_file", {"path": "hidden_tests.py"})["ok"]
    assert not session.call("read_file", {"path": "../reference/shop/cart.py"})["ok"]
    assert not session.call("run_shell", {"command": "anything"})["ok"]
    assert not session.call("run_public_tests", {"hidden": True})["ok"]
    paths = {file["path"] for file in session.call("list_files", {})["files"]}
    assert "public_tests.py" in paths and "hidden_tests.py" not in paths


def test_external_stage_controls_writes_and_guards_readonly_files():
    workspace = Workspace(FIXTURE)
    session = ToolSession(workspace, lambda *_: {})
    change = {"files": {"shop/money.py": "def amount(text): return 0"}}
    assert not session.call("write_files", change)["ok"]
    session.enter_stage(Stage.IMPLEMENT)
    assert session.call("write_files", change)["ok"]
    assert not session.call("write_files", {"files": {"public_tests.py": ""}})["ok"]
    session.enter_stage(Stage.VERIFY)
    assert not session.call("write_files", change)["ok"]


def test_public_test_budget_is_global_across_phases_and_results_are_filtered():
    calls = []

    def grade(workspace, number):
        calls.append(number)
        return {"status": "passed", "tests": 2, "failures": 0, "private_debug": "not_for_model"}

    session = ToolSession(Workspace(FIXTURE), grade, max_public_runs=1)
    result = session.call("run_public_tests", {})
    assert result["ok"] and "private_debug" not in result["grading"]
    session.enter_stage(Stage.VERIFY)
    assert not session.call("run_public_tests", {})["ok"]
    assert calls == [1]


def test_exact_replacement_obeys_phase_permissions_and_rolls_back_invalid_patch():
    workspace = Workspace(FIXTURE)
    session = ToolSession(workspace, lambda *_: {})
    path = "shop/money.py"
    original = workspace.read_file(path)
    patch = {"path": path, "old": original, "new": "def amount(text): return 0\n"}
    assert not session.call("replace_in_file", patch)["ok"]
    session.enter_stage(Stage.IMPLEMENT)
    assert not session.call("replace_in_file", {**patch, "new": "def broken("})["ok"]
    assert workspace.read_file(path) == original
    assert not session.call("replace_in_file", {**patch, "old": "missing text"})["ok"]
    assert not session.call("replace_in_file", {**patch, "old": ""})["ok"]
    assert session.call("replace_in_file", patch)["ok"]
    session.enter_stage(Stage.VERIFY)
    assert not session.call("replace_in_file", patch)["ok"]
