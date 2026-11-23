"""An in-memory, allowlisted multi-file workspace prototype. Never execute candidate Python."""

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath

MAX_FILES = 16
MAX_BYTES = 65536


def relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "\x00" in value:
        raise ValueError("Expected a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("Path traversal and non-canonical paths are forbidden")
    return str(path)


def trusted_file(root: Path, value: str) -> str:
    relative = relative_path(value)
    path = root / relative
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlinked task files are not supported")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Task file leaves its root")
    return path.read_text(encoding="utf-8-sig")


class Workspace:
    def __init__(self, manifest: Path):
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        expected = {
            "schema_version",
            "id",
            "project",
            "visible",
            "editable",
            "instruction",
            "adapter",
            "public_grader",
            "hidden_grader",
        }
        if set(data) != expected or data["schema_version"] != 1:
            raise ValueError("Unsupported repository task manifest")
        root = manifest.resolve().parent
        project = root / relative_path(data["project"])
        if project.is_symlink() or not project.resolve().is_relative_to(root):
            raise ValueError("Project directory must stay within task root")
        visible = [relative_path(path) for path in data["visible"]]
        editable = [relative_path(path) for path in data["editable"]]
        if len(set(visible)) != len(visible) or not 1 <= len(visible) <= MAX_FILES:
            raise ValueError("Duplicate or excessive visible files")
        if not editable or len(set(editable)) != len(editable) or not set(editable) <= set(visible):
            raise ValueError("Editable files must be a nonempty subset of visible files")
        if any(not path.endswith(".py") or path == "candidate.py" for path in editable):
            raise ValueError("Only declared Python implementation files may be edited")
        if "candidate.py" in visible:
            raise ValueError("candidate.py is reserved for the trusted adapter")
        self.task_id = data["id"]
        self.editable = frozenset(editable)
        self._files = {path: trusted_file(project, path) for path in visible}
        self.instruction = trusted_file(root, data["instruction"])
        self.adapter = trusted_file(root, data["adapter"])
        self.public_grader = trusted_file(root, data["public_grader"])
        self.hidden_grader = trusted_file(root, data["hidden_grader"])
        self._validate_size(self._files)
        self.initial_fingerprint = self.fingerprint()

    @staticmethod
    def _validate_size(files: dict):
        if sum(len(text.encode("utf-8")) for text in files.values()) > MAX_BYTES:
            raise ValueError("Workspace exceeds 64 KiB")

    def list_files(self) -> list[dict]:
        return [
            {
                "path": path,
                "editable": path in self.editable,
                "bytes": len(self._files[path].encode("utf-8")),
            }
            for path in sorted(self._files)
        ]

    def read_file(self, path: str) -> str:
        path = relative_path(path)
        if path not in self._files:
            raise ValueError("File is not in the visible inventory")
        return self._files[path]

    def write_files(self, changes: dict[str, str]) -> None:
        if not isinstance(changes, dict) or not changes:
            raise ValueError("Expected a nonempty file mapping")
        staged = dict(self._files)
        for path, content in changes.items():
            path = relative_path(path)
            if path not in self.editable:
                raise ValueError("File is not editable")
            if not isinstance(content, str):
                raise ValueError("File content must be text")
            ast.parse(content, filename=path)
            staged[path] = content
        self._validate_size(staged)
        self._files = staged

    def snapshot(self) -> dict[str, str]:
        return {path: text for path, text in self._files.items() if path.endswith(".py")}

    def fingerprint(self) -> str:
        value = {
            "task": self.task_id,
            "files": self._files,
            "editable": sorted(self.editable),
            "instruction": self.instruction,
            "adapter": self.adapter,
            "public_grader": self.public_grader,
            "hidden_grader": self.hidden_grader,
        }
        return hashlib.sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
