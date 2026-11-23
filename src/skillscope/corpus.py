"""Validate known-correct references and broken starters before paid experiments."""

from pathlib import Path

from skillscope.batch import write_json
from skillscope.loader import load_experiment, read_input
from skillscope.models import ExperimentSpec
from skillscope.sandbox import grade, preflight


def check_corpus(config: Path, docker: str, output: Path) -> dict:
    experiment = load_experiment(config)
    spec = ExperimentSpec.model_validate_json(config.read_text(encoding="utf-8-sig"))
    image = preflight(docker)
    output.mkdir(parents=True, exist_ok=False)
    records = []
    for task in spec.tasks:
        grader = read_input(config.resolve().parent, task.grader_file)
        for kind, path, expected in (
            ("reference", Path(f"references/{task.id}.py"), "passed"),
            ("starter", task.starter_file, "failed"),
        ):
            directory = output / task.id / kind
            directory.mkdir(parents=True)
            result = grade(
                read_input(config.resolve().parent, path), grader, docker, image, directory
            )
            records.append({"task": task.id, "kind": kind, "expected": expected, "grading": result})
            print(f"评分器校验：{task.id} {kind} {result['status']}", flush=True)
    summary = {
        "experiment_sha256": experiment.sha256,
        "sandbox_image_id": image,
        "passed": all(item["grading"]["status"] == item["expected"] for item in records),
        "records": records,
        "model_calls": 0,
    }
    write_json(output / "corpus-check.json", summary)
    return summary
