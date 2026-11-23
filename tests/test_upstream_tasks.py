import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts.repo_execution import grade_workspace
from scripts.repo_workspace import Workspace
from skillscope.sandbox import preflight

ROOT = Path(__file__).resolve().parents[1] / "benchmarks/upstream"


def test_upstream_sources_are_pinned_and_holdout_split_is_fixed():
    collection = json.loads((ROOT / "collection.json").read_text())
    assert [(t["id"], t["split"]) for t in collection["tasks"]] == [
        ("dotenv-backslash", "discovery"),
        ("dotenv-comment", "discovery"),
        ("dotenv-bom", "holdout"),
    ]
    for task in collection["tasks"]:
        directory = ROOT / task["id"]
        provenance = json.loads((directory / "provenance.json").read_text())
        workspace = Workspace(directory / "task.json")
        assert workspace.execution_mode == "directory"
        for path, item in provenance["source_files"].items():
            raw = (directory / "project" / path).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == item["sha256"]
            assert (
                hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
                == item["git_blob"]
            )
        assert "Redistribution and use" in workspace.read_file("LICENSE")


@pytest.mark.skipif(not os.environ.get("SKILLSCOPE_TEST_DOCKER"), reason="Opt-in real Docker")
@pytest.mark.parametrize(
    "task_id, public_count, hidden_count", [("dotenv-backslash", 2, 13), ("dotenv-comment", 2, 9)]
)
def test_discovery_regressions_and_upstream_reference(
    task_id, public_count, hidden_count, tmp_path
):
    # Holdout is deliberately excluded from grading and calibration.
    docker = os.environ["SKILLSCOPE_TEST_DOCKER"]
    image = preflight(docker)
    directory = ROOT / task_id
    workspace = Workspace(directory / "task.json")
    original = grade_workspace(workspace, docker, image, tmp_path / "original")
    assert original["status"] == "failed" and original["tests"] == public_count
    workspace.write_files(
        {
            path: (directory / "reference" / path).read_text(encoding="utf-8")
            for path in workspace.editable
        }
    )
    public = grade_workspace(workspace, docker, image, tmp_path / "reference-public")
    hidden = grade_workspace(workspace, docker, image, tmp_path / "reference-hidden", hidden=True)
    assert public["status"] == "passed" and public["tests"] == public_count
    assert hidden["status"] == "passed" and hidden["tests"] == hidden_count
