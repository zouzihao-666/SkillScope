"""Vendor pinned upstream library tasks without importing or executing their code."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

TASKS = [
    {
        "id": "dotenv-backslash",
        "split": "discovery",
        "base": "751f8c148222e58aa173c83c4e5e6cfccb2cc124",
        "fix": "f7b18d9c72d1abcc2ad4023424b84f5bee30d266",
        "issue": 661,
        "editable": ["dotenv/main.py", "dotenv/parser.py"],
    },
    {
        "id": "dotenv-comment",
        "split": "discovery",
        "base": "49515afee2d50c33cad9419b3800b3a0dc93fc59",
        "fix": "f5485a61eefa5e686d6d5bdc7aa9ad6b104b1e92",
        "issue": 600,
        "editable": ["dotenv/parser.py"],
    },
    {
        "id": "dotenv-bom",
        "split": "holdout",
        "base": "68ea2d10dd8e97e6dea67c32742085f27729e3fe",
        "fix": "bca6644d9aedbe287b792b756b3ae3d650cd0d3a",
        "issue": 637,
        "editable": ["dotenv/parser.py"],
    },
]
REPOSITORY = "https://github.com/theskumar/python-dotenv"


def git(repository: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-c", "http.sslBackend=openssl", "-C", str(repository), *args],
        check=True,
        capture_output=True,
        timeout=60,
    ).stdout


def export(repository: Path, destination: Path):
    for task in TASKS:
        # Parent identity is checked rather than trusting a mutable tag or branch.
        if git(repository, "rev-parse", task["fix"] + "^").decode().strip() != task["base"]:
            raise ValueError("Unexpected upstream fix parent")
        root = destination / task["id"]
        (root / "project").mkdir(parents=True, exist_ok=False)
        inventory, hashes = [], {}
        paths = git(repository, "ls-tree", "-r", "--name-only", task["base"], "src/dotenv")
        for upstream in [*paths.decode().splitlines(), "LICENSE"]:
            path = upstream.removeprefix("src/")
            raw = git(repository, "show", task["base"] + ":" + upstream)
            raw.decode("utf-8")  # Reject binary sources; preserve upstream bytes.
            target = root / "project" / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            inventory.append(path)
            hashes[path] = {
                "upstream_path": upstream,
                "git_blob": git(repository, "rev-parse", task["base"] + ":" + upstream)
                .decode()
                .strip(),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        for path in task["editable"]:
            reference = root / "reference" / path
            reference.parent.mkdir(parents=True, exist_ok=True)
            reference.write_bytes(git(repository, "show", task["fix"] + ":src/" + path))
        provenance = {
            **task,
            "repository": REPOSITORY,
            "issue_url": f"{REPOSITORY}/issues/{task['issue']}",
            "fix_url": f"{REPOSITORY}/commit/{task['fix']}",
            "license": "BSD-3-Clause; original LICENSE retained in each project",
            "projection": "All src/dotenv files mapped to dotenv; LICENSE retained. No CLI dependencies installed.",
            "grading": "SkillScope-authored regression checks, not the complete upstream suite",
            "source_files": hashes,
        }
        manifest = {
            "schema_version": 1,
            "id": task["id"],
            "execution_mode": "directory",
            "project": "project",
            "visible": inventory,
            "editable": task["editable"],
            "instruction": "instruction.md",
            "adapter": "adapter.py",
            "public_grader": "public_tests.py",
            "hidden_grader": "hidden_tests.py",
        }
        for name, value in (("provenance.json", provenance), ("task.json", manifest)):
            (root / name).write_bytes((json.dumps(value, indent=2) + "\n").encode())
    (destination / "collection.json").write_bytes(
        (json.dumps({"schema_version": 1, "tasks": TASKS}, indent=2) + "\n").encode()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--destination", type=Path, default=Path("benchmarks/upstream"))
    arguments = parser.parse_args()
    export(arguments.repository, arguments.destination)


if __name__ == "__main__":
    main()
