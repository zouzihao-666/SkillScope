"""Frozen, resumable, budgeted exploratory batches. No automatic paid retries."""

import json
import math
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from skillscope.loader import canonical_json, digest, load_experiment, read_input
from skillscope.models import ExperimentSpec
from skillscope.planner import build_plan
from skillscope.runner import run_task
from skillscope.sandbox import preflight
from skillscope.settings import Settings

PRICE = {
    "currency": "USD",
    "cache_hit_per_million": 0.006,
    "cache_miss_per_million": 0.30,
    "output_per_million": 1.20,
    "source": "https://api-docs.deepseek.com/quick_start/pricing/",
    "verified_date": "2026-11-23",
    "kind": "peak_rate_upper_estimate_not_invoice",
}


@dataclass(frozen=True)
class Limits:
    max_calls: int = 444
    max_reported_tokens: int = 1_000_000
    max_estimated_usd: float = 1.0
    max_output_tokens: int = 1024
    workers: int = 3

    def validate(self):
        if not (1 <= self.workers <= 4 and 128 <= self.max_output_tokens <= 4096):
            raise ValueError("workers must be 1..4 and output tokens 128..4096")
        if self.max_calls < 3 or self.max_reported_tokens < 1:
            raise ValueError("Positive token budget and at least three calls required")
        if not math.isfinite(self.max_estimated_usd) or self.max_estimated_usd <= 0:
            raise ValueError("Positive finite cost estimate limit required")


def write_json(path: Path, value) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def source_fingerprint() -> str:
    root = Path(__file__).parent
    return digest(
        canonical_json(
            {
                str(path.relative_to(root)).replace("\\", "/"): digest(
                    path.read_text(encoding="utf-8")
                )
                for path in sorted(root.rglob("*.py"))
            }
        )
    )


def estimate_cost(tokens: dict, cache_hits: int = 0) -> float:
    prompt = tokens.get("prompt_tokens", 0) or 0
    output = tokens.get("completion_tokens", 0) or 0
    cache_hits = min(prompt, max(0, cache_hits))
    return (
        (prompt - cache_hits) * PRICE["cache_miss_per_million"]
        + cache_hits * PRICE["cache_hit_per_million"]
        + output * PRICE["output_per_million"]
    ) / 1_000_000


def trace_cost(directory: Path, result: dict) -> float:
    events = directory / "trace.jsonl"
    if not events.exists():
        return estimate_cost(result.get("reported_tokens", {}))
    cost = 0.0
    for line in events.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event["type"] == "response":
            usage = event["response"].get("usage") or {}
            cost += estimate_cost(usage, usage.get("prompt_cache_hit_tokens", 0) or 0)
    return cost


def reservation(limits: Limits) -> tuple[int, int, float]:
    # Backend rejects message/tool JSON above 64 KiB. Reserve extra framing units.
    # This is a conservative byte-based tokenizer approximation, not an invoice guarantee.
    inputs = 3 * (65536 + 1024)
    outputs = 3 * limits.max_output_tokens
    return (
        3,
        inputs + outputs,
        estimate_cost({"prompt_tokens": inputs, "completion_tokens": outputs}),
    )


def can_start(results: list[dict], pending: int, limits: Limits) -> bool:
    calls, tokens, cost = reservation(limits)
    return (
        sum(item["calls_attempted"] for item in results) + (pending + 1) * calls <= limits.max_calls
        and sum(item["reported_tokens"]["total_tokens"] for item in results)
        + (pending + 1) * tokens
        <= limits.max_reported_tokens
        and sum(item["estimated_usd_upper"] for item in results) + (pending + 1) * cost
        <= limits.max_estimated_usd + 1e-12
    )


def freeze_config(config: Path, destination: Path) -> Path:
    config = config.resolve()
    spec = ExperimentSpec.model_validate_json(config.read_text(encoding="utf-8-sig"))
    destination.mkdir()
    paths = [item.file for item in spec.skills]
    for task in spec.tasks:
        paths.extend((task.instruction_file, task.starter_file, task.grader_file))
    for relative in paths:
        text = read_input(config.parent, relative)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    frozen = destination / "experiment.json"
    frozen.write_text(spec.model_dump_json(indent=2), encoding="utf-8")
    if load_experiment(frozen).sha256 != load_experiment(config).sha256:
        raise ValueError("Frozen inputs do not match original experiment")
    return frozen


def run_batch(
    config: Path,
    settings: Settings,
    output: Path,
    limits: Limits = Limits(),
    repeats: int = 3,
    seed: int = 731,
    resume: bool = False,
) -> dict:
    limits.validate()
    if repeats < 2:
        raise ValueError("Exploratory batches require at least two repetitions")
    if load_experiment(config).model != "deepseek-flash":
        raise ValueError("This price schedule is only for deepseek-flash")
    image = preflight(settings.docker)
    if resume:
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        if manifest["limits"] != asdict(limits):
            raise ValueError("Resume limits differ from the frozen batch")
        if (
            manifest["source_sha256"] != source_fingerprint()
            or manifest["sandbox_image_id"] != image
        ):
            raise ValueError("Resume source or sandbox image changed")
        frozen = output / "frozen/experiment.json"
        if manifest["experiment_sha256"] != load_experiment(frozen).sha256:
            raise ValueError("Frozen input content changed")
        if manifest["plan"]["repeats"] != repeats or manifest["plan"]["order_seed"] != seed:
            raise ValueError("Resume seed/repeats differ from the frozen batch")
    else:
        experiment = load_experiment(config)
        if not 6 <= len(experiment.skills) <= 10:
            raise ValueError("Stage 3 requires 6..10 skills")
        if sum(task.split == "discovery" for task in experiment.tasks) < 4:
            raise ValueError("Stage 3 requires at least four discovery tasks")
        output.mkdir(parents=True, exist_ok=False)
        frozen = freeze_config(config, output / "frozen")
        plan = build_plan(experiment, repeats=repeats, seed=seed, controls=True)
        manifest = {
            "schema_version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "experiment_sha256": experiment.sha256,
            "source_sha256": source_fingerprint(),
            "sandbox_image_id": image,
            "limits": asdict(limits),
            "pricing": PRICE,
            "plan": plan,
            "plan_sha256": digest(canonical_json(plan)),
            "pilot": {
                "minimum_success_fraction": 0.5,
                "tasks": [task.id for task in experiment.tasks if task.split == "discovery"],
            },
            "order": "pilot_then_fully_shuffled_main; pilot_excluded_from_main_statistics",
        }
        write_json(output / "manifest.json", manifest)
    if manifest["plan_sha256"] != digest(canonical_json(manifest["plan"])):
        raise ValueError("Stored plan has changed")
    jobs = [
        {
            "id": f"pilot__{task}",
            "task_id": task,
            "condition_id": "baseline",
            "repeat": 0,
            "phase": "pilot",
        }
        for task in manifest["pilot"]["tasks"]
    ] + [{**job, "phase": "main"} for job in manifest["plan"]["runs"]]
    if len({job["id"] for job in jobs}) != len(jobs):
        raise ValueError("Plan contains ambiguous run identifiers")
    if len(jobs) * 3 > limits.max_calls:
        raise ValueError("Call budget cannot cover the planned batch")
    results = []
    for job in jobs:
        directory = output / "runs" / job["id"]
        if not directory.exists():
            continue
        if not (directory / "run.json").exists():
            raise ValueError(
                "Incomplete run directory found; billing is unknown, no automatic retry"
            )
        result = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        if result["experiment_sha256"] != manifest["experiment_sha256"]:
            raise ValueError("Stored run has a different input fingerprint")
        results.append({**result, "job": job, "estimated_usd_upper": trace_cost(directory, result)})
    lease = output / ".active"
    with lease.open("x", encoding="utf-8") as stream:
        stream.write(datetime.now(UTC).isoformat())
    status, reason = "running", None
    started = time.monotonic()

    def checkpoint():
        completed = {item["job"]["id"] for item in results}
        write_json(
            output / "batch.json",
            {
                "status": status,
                "stop_reason": reason,
                "completed": len(results),
                "planned": len(jobs),
                "main_completed": sum(item["job"]["phase"] == "main" for item in results),
                "calls_attempted": sum(item["calls_attempted"] for item in results),
                "reported_tokens": sum(item["reported_tokens"]["total_tokens"] for item in results),
                "estimated_usd_upper": sum(item["estimated_usd_upper"] for item in results),
                "usage_complete": all(item["usage_complete"] for item in results),
                "remaining_ids": [job["id"] for job in jobs if job["id"] not in completed],
                "elapsed_this_session_seconds": round(time.monotonic() - started, 3),
            },
        )
        with (output / "results.jsonl").open("w", encoding="utf-8") as stream:
            for item in results:
                stream.write(json.dumps(item, ensure_ascii=False) + "\n")

    def execute(job):
        result = run_task(
            frozen,
            job["task_id"],
            job["condition_id"],
            settings,
            output / "runs" / job["id"],
            max_tokens=limits.max_output_tokens,
            quiet=True,
        )
        if result["sandbox_image_id"] != image:
            raise ValueError("Sandbox image changed during the batch")
        return {
            **result,
            "job": job,
            "estimated_usd_upper": trace_cost(output / "runs" / job["id"], result),
        }

    try:
        if any(not item["usage_complete"] for item in results):
            status, reason = "stopped", "previous_usage_unknown_no_retry"
        else:
            for phase in ("pilot", "main"):
                completed_ids = {item["job"]["id"] for item in results}
                remaining = [
                    job for job in jobs if job["phase"] == phase and job["id"] not in completed_ids
                ]
                index = 0
                with ThreadPoolExecutor(max_workers=limits.workers) as pool:
                    pending = {}
                    while index < len(remaining) or pending:
                        while (
                            status == "running"
                            and index < len(remaining)
                            and len(pending) < limits.workers
                            and can_start(results, len(pending), limits)
                        ):
                            job = remaining[index]
                            pending[pool.submit(execute, job)] = job
                            index += 1
                        if not pending:
                            if index < len(remaining):
                                status, reason = "stopped", "budget_reservation_limit"
                            break
                        done, _ = wait(pending, return_when=FIRST_COMPLETED)
                        for future in done:
                            job = pending.pop(future)
                            try:
                                result = future.result()
                            except Exception:
                                # No paid retry and no invented run record.
                                status, reason = "stopped", f"worker_error:{job['id']}"
                                continue
                            results.append(result)
                            print(
                                f"批次 {len(results)}/{len(jobs)}：{job['id']} {result['status']}",
                                flush=True,
                            )
                            if not result["usage_complete"] or result["status"] in (
                                "api_error",
                                "infrastructure_error",
                                "internal_error",
                                "interrupted",
                            ):
                                status, reason = (
                                    "stopped",
                                    "provider_or_infrastructure_error_no_retry",
                                )
                            checkpoint()
                        if status != "running" and not pending:
                            break
                if status != "running":
                    break
                if phase == "pilot":
                    pilot = [item for item in results if item["job"]["phase"] == "pilot"]
                    if (
                        sum(item["status"] == "passed" for item in pilot) / len(pilot)
                        < manifest["pilot"]["minimum_success_fraction"]
                    ):
                        status, reason = "stopped", "baseline_gate_failed"
                        break
            if status == "running":
                status = "completed" if len(results) == len(jobs) else "stopped"
    except BaseException:
        status, reason = "interrupted", "inspect_before_resume"
        raise
    finally:
        checkpoint()
        lease.unlink(missing_ok=True)
    return json.loads((output / "batch.json").read_text(encoding="utf-8"))
