import os
from pathlib import Path

import pytest

from skillscope.loader import load_experiment
from skillscope.models import ExperimentSpec
from skillscope.sandbox import grade, preflight

ROOT = Path(__file__).resolve().parents[1] / "benchmarks/stage3"
SPEC = ExperimentSpec.model_validate_json((ROOT / "experiment.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.skipif(
    not os.environ.get("SKILLSCOPE_TEST_DOCKER"),
    reason="Opt-in Docker corpus checks; no model API calls",
)


@pytest.mark.parametrize("task", SPEC.tasks, ids=lambda task: task.id)
def test_correct_reference_passes_and_broken_starter_fails(task, tmp_path):
    assert len(load_experiment(ROOT / "experiment.json").tasks) == 6
    docker = os.environ["SKILLSCOPE_TEST_DOCKER"]
    image = preflight(docker)
    grader = (ROOT / task.grader_file).read_text(encoding="utf-8")
    for kind, path, expected in (
        ("reference", ROOT / f"references/{task.id}.py", "passed"),
        ("starter", ROOT / task.starter_file, "failed"),
    ):
        output = tmp_path / kind
        output.mkdir()
        result = grade(path.read_text(encoding="utf-8"), grader, docker, image, output)
        assert result["status"] == expected
