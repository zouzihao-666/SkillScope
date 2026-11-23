"""Run a reference-patch multi-file demonstration. No model API is called."""

import argparse
from pathlib import Path

from scripts.repo_execution import grade_workspace
from scripts.repo_tools import ToolSession
from scripts.repo_workspace import Workspace
from skillscope.batch import write_json
from skillscope.models import Stage
from skillscope.sandbox import preflight
from skillscope.settings import find_docker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task", type=Path, default=Path("benchmarks/repo-prototype/cart/task.json")
    )
    parser.add_argument("--output", type=Path, default=Path("results/repo-prototype-demo"))
    arguments = parser.parse_args()
    output = arguments.output
    docker = find_docker()
    image = preflight(docker)
    workspace = Workspace(arguments.task)
    output.mkdir(parents=True, exist_ok=False)
    initial = grade_workspace(workspace, docker, image, output / "initial-public")
    session = ToolSession(
        workspace,
        lambda current, number: grade_workspace(
            current, docker, image, output / f"public-{number}"
        ),
    )
    inventory = session.call("list_files", {})
    public_source = session.call("read_file", {"path": "public_tests.py"})
    session.enter_stage(Stage.IMPLEMENT)
    reference = arguments.task.parent / "reference"
    changes = {path: (reference / path).read_text(encoding="utf-8") for path in workspace.editable}
    updated = session.call("write_files", {"files": changes})
    public = session.call("run_public_tests", {})
    session.enter_stage(Stage.VERIFY)
    hidden = grade_workspace(workspace, docker, image, output / "hidden", hidden=True)
    record = {
        "task": workspace.task_id,
        "model_calls": 0,
        "repair_origin": "manually_authored_reference_not_a_model_generated_patch",
        "prototype_scope": "Python import-only virtual modules; not a physical repository runner",
        "sandbox_image_id": image,
        "inventory": inventory,
        "public_tests_readable": public_source["ok"],
        "initial_public": initial,
        "reference_update": updated,
        "fixed_public": public["grading"],
        "hidden": hidden,
    }
    write_json(output / "demo.json", record)
    passed = (
        initial["status"] == "failed"
        and updated["ok"]
        and public["grading"]["status"] == "passed"
        and hidden["status"] == "passed"
    )
    print(f"Reference-patch demonstration passed: {passed}; model calls: 0; {output / 'demo.json'}")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
