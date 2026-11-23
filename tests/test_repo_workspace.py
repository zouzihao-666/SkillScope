import json
from pathlib import Path
from shutil import copytree

import pytest

from scripts.repo_workspace import Workspace, relative_path

FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks/repo-prototype/cart"


def test_inventory_excludes_graders_and_adapter_and_snapshot_excludes_readme():
    workspace = Workspace(FIXTURE / "task.json")
    paths = {item["path"] for item in workspace.list_files()}
    assert paths == {"shop/__init__.py", "shop/money.py", "shop/cart.py", "README.md"}
    assert set(workspace.snapshot()) == paths - {"README.md"}
    for path in ("hidden_tests.py", "public_tests.py", "adapter.py", ".env"):
        with pytest.raises(ValueError):
            workspace.read_file(path)


@pytest.mark.parametrize(
    "path",
    [
        "../secret.py",
        "/etc/passwd",
        "C:/secret.py",
        "a\\b.py",
        "a/../b.py",
        "./a.py",
        "a//b.py",
        "a.py:stream",
        "",
    ],
)
def test_cross_platform_paths_reject_escapes(path):
    with pytest.raises(ValueError):
        relative_path(path)


def test_file_updates_are_atomic_and_do_not_modify_original_fixture():
    workspace = Workspace(FIXTURE / "task.json")
    old = workspace.read_file("shop/money.py")
    with pytest.raises(ValueError):
        workspace.write_files(
            {"shop/money.py": "def amount(text): return 0", "hidden_tests.py": "assert True"}
        )
    assert workspace.read_file("shop/money.py") == old
    with pytest.raises(SyntaxError):
        workspace.write_files({"shop/money.py": "def incomplete("})
    assert workspace.read_file("shop/money.py") == old
    fingerprint = workspace.fingerprint()
    workspace.write_files({"shop/money.py": "def amount(text):\n    return 0\n"})
    assert workspace.fingerprint() != fingerprint
    assert (FIXTURE / "project/shop/money.py").read_text() == old


def test_size_limit_and_readonly_implementation_are_enforced():
    workspace = Workspace(FIXTURE / "task.json")
    with pytest.raises(ValueError):
        workspace.write_files({"shop/__init__.py": ""})
    with pytest.raises(ValueError, match="64 KiB"):
        workspace.write_files({"shop/money.py": "#" + "x" * 65536})


def test_manifest_cannot_mark_a_grader_as_editable(tmp_path):
    copytree(FIXTURE, tmp_path / "task")
    path = tmp_path / "task/task.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["editable"].append("hidden_tests.py")
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="subset"):
        Workspace(path)
