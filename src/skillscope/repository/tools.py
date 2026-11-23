"""A small JSON tool controller for the repository-workspace prototype."""

from skillscope.models import Stage
from skillscope.repository.workspace import Workspace


class ToolSession:
    def __init__(self, workspace: Workspace, public_grader, max_public_runs: int = 2):
        self.workspace = workspace
        self.public_grader = public_grader
        self.max_public_runs = max_public_runs
        self.public_runs = 0
        self.stage = Stage.INVESTIGATE

    def enter_stage(self, stage: Stage):
        self.stage = Stage(stage)

    def call(self, name: str, arguments: dict) -> dict:
        expected = {
            "list_files": set(),
            "read_file": {"path"},
            "write_files": {"files"},
            "write_file": {"path", "content"},
            "replace_in_file": {"path", "old", "new"},
            "run_public_tests": set(),
        }
        if (
            name not in expected
            or not isinstance(arguments, dict)
            or set(arguments) != expected[name]
        ):
            return {"ok": False, "error": "Unknown tool or invalid argument fields"}
        try:
            if name == "list_files":
                return {
                    "ok": True,
                    "files": [
                        *self.workspace.list_files(),
                        {
                            "path": "public_tests.py",
                            "editable": False,
                            "bytes": len(self.workspace.public_grader.encode("utf-8")),
                        },
                    ],
                }
            if name == "read_file":
                path = arguments["path"]
                content = (
                    self.workspace.public_grader
                    if path == "public_tests.py"
                    else self.workspace.read_file(path)
                )
                return {"ok": True, "content": content}
            if name in ("write_files", "write_file", "replace_in_file"):
                if self.stage != Stage.IMPLEMENT:
                    return {
                        "ok": False,
                        "error": "Writes are allowed only in the implementation phase",
                    }
                if name in ("write_file", "replace_in_file") and not isinstance(
                    arguments["path"], str
                ):
                    raise ValueError("File path must be text")
                if name == "replace_in_file":
                    self.workspace.replace_in_file(
                        arguments["path"], arguments["old"], arguments["new"]
                    )
                    return {"ok": True, "fingerprint": self.workspace.fingerprint()}
                changes = (
                    arguments["files"]
                    if name == "write_files"
                    else {arguments["path"]: arguments["content"]}
                )
                self.workspace.write_files(changes)
                return {"ok": True, "fingerprint": self.workspace.fingerprint()}
            if self.public_runs >= self.max_public_runs:
                return {"ok": False, "error": "Public test budget exhausted"}
            self.public_runs += 1
            result = self.public_grader(self.workspace, self.public_runs)
            return {
                "ok": True,
                "grading": {key: result.get(key) for key in ("status", "tests", "failures")},
            }
        except (ValueError, SyntaxError) as error:
            return {"ok": False, "error": f"{type(error).__name__}: {error}"}
