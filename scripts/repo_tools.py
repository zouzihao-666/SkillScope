"""A small JSON tool controller for the repository-workspace prototype."""

from scripts.repo_workspace import Workspace
from skillscope.models import Stage


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
            if name == "write_files":
                if self.stage != Stage.IMPLEMENT:
                    return {
                        "ok": False,
                        "error": "Writes are allowed only in the implementation phase",
                    }
                self.workspace.write_files(arguments["files"])
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
