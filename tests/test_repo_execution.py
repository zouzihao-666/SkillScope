import ast
import os
from pathlib import Path

import pytest

from scripts.repo_execution import bundle, grade_workspace
from scripts.repo_workspace import Workspace
from skillscope.sandbox import preflight

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "benchmarks/repo-prototype/cart"


def test_bundling_never_imports_candidate_code_on_the_host():
    workspace = Workspace(FIXTURE / "task.json")
    workspace.write_files({"shop/money.py": "raise RuntimeError('container-only execution')\n"})
    code = bundle(workspace)
    ast.parse(code)
    assert "container-only execution" in code
    assert "def checkout" in code
    assert workspace.hidden_grader not in code and workspace.public_grader not in code


@pytest.mark.skipif(not os.environ.get("SKILLSCOPE_TEST_DOCKER"), reason="Opt-in real Docker")
def test_multifile_original_fails_and_reference_passes_both_graders(tmp_path):
    docker = os.environ["SKILLSCOPE_TEST_DOCKER"]
    image = preflight(docker)
    workspace = Workspace(FIXTURE / "task.json")
    original = grade_workspace(workspace, docker, image, tmp_path / "original")
    assert original["status"] == "failed" and original["tests"] == 2
    workspace.write_files(
        {
            path: (FIXTURE / "reference" / path).read_text(encoding="utf-8")
            for path in workspace.editable
        }
    )
    public = grade_workspace(workspace, docker, image, tmp_path / "fixed-public")
    hidden = grade_workspace(workspace, docker, image, tmp_path / "fixed-hidden", hidden=True)
    assert public["status"] == "passed" and public["tests"] == 2
    assert hidden["status"] == "passed" and hidden["tests"] == 19
