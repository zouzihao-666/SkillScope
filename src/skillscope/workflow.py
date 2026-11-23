"""One-command repeated diagnosis, policy construction and frozen holdout validation."""

import hashlib
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

from skillscope.batch import estimate_cost, source_fingerprint, write_json
from skillscope.diagnostics import (
    BudgetExhausted,
    Measurement,
    policy_from_suspects,
    reduce_combination,
)
from skillscope.loader import digest
from skillscope.models import Condition, Skill, Stage
from skillscope.repo_config import DiagnosisSpec, freeze_repository_inputs, load_repository_config
from skillscope.repository.agent import MAX_OUTPUT, run_agent
from skillscope.repository.workspace import Workspace
from skillscope.sandbox import preflight
from skillscope.settings import Settings


@contextmanager
def workflow_lock(root: Path):
    """OS-owned lock releases after a crash; a stale file cannot trigger retries."""
    with (root / "workflow.lock").open("a+b") as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise ValueError("Another diagnosis process already owns this output") from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def full_policy(ids: tuple[str, ...]) -> dict:
    return {stage.value: list(ids) for stage in Stage}


def policy_key(task: str, policy: dict) -> str:
    return digest(json.dumps({"task": task, "policy": policy}, sort_keys=True))[:20]


class DiagnosisWorkflow:
    def __init__(self, root: Path, settings: Settings | None, evaluator=run_agent):
        self.root, self.settings, self.evaluator = root, settings, evaluator
        self.plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
        self.spec = DiagnosisSpec.model_validate(self.plan["spec"])
        self.skills = tuple(Skill.model_validate(item) for item in self.plan["skills"])
        self.ids = tuple(skill.id for skill in self.skills)
        self.declared = {
            skill.id: tuple(stage.value for stage in skill.stages) for skill in self.skills
        }
        self.state = json.loads((root / "state.json").read_text(encoding="utf-8"))
        if (
            hashlib.sha256((root / "plan.json").read_bytes()).hexdigest()
            != self.state["plan_sha256"]
        ):
            raise ValueError("Plan bytes changed after freeze")
        self.reservation = estimate_cost(
            {
                "prompt_tokens": self.spec.limits.per_run_calls * (65536 + 1024),
                "completion_tokens": self.spec.limits.per_run_calls * MAX_OUTPUT,
            }
        )

    def save(self):
        self.state["budget"] = self.budget()
        write_json(self.root / "state.json", self.state)

    def budget(self) -> dict:
        known, uncertain, calls, logged, tokens = 0.0, 0.0, 0, 0, 0
        for trial in self.state["trials"]:
            result = trial.get("result")
            if result and result["usage_complete"]:
                known += result["estimated_usd_upper"]
                calls += result["calls_attempted"]
            else:
                uncertain += trial["reserved_usd"]
                calls += self.spec.limits.per_run_calls
            if result:
                logged += result["calls_attempted"]
                tokens += result["reported_tokens"]["total_tokens"]
        return {
            "known_response_estimate_usd": known,
            "unknown_reserved_usd": uncertain,
            "conservative_cost_bound_usd": known + uncertain,
            "charged_or_reserved_calls": calls,
            "logged_call_attempts": logged,
            "reported_tokens": tokens,
            "usage_complete": all(
                trial.get("result", {}).get("usage_complete", False)
                for trial in self.state["trials"]
            ),
        }

    def capacity(self, reserve_runs=0):
        if any(
            trial.get("result") and not trial["result"]["usage_complete"]
            for trial in self.state["trials"]
        ):
            self.state["stop_reason"] = "unknown_usage"
            raise BudgetExhausted("Unknown usage stops additional calls")
        budget = self.budget()
        needed = reserve_runs + 1
        limits = self.spec.limits
        if (
            len(self.state["trials"]) + needed > limits.max_runs
            or budget["charged_or_reserved_calls"] + needed * limits.per_run_calls
            > limits.max_calls
            or budget["conservative_cost_bound_usd"] + self.reservation > limits.max_usd
        ):
            raise BudgetExhausted("Remaining quota cannot reserve this complete trial")

    def verify_source(self, task):
        if source_fingerprint() != self.plan["source_sha256"]:
            raise ValueError("Execution source changed after plan freeze")
        if (
            hashlib.sha256((self.root / "plan.json").read_bytes()).hexdigest()
            != self.state["plan_sha256"]
        ):
            raise ValueError("Plan changed during execution")
        if (
            Workspace(self.root / "inputs" / task["id"] / "task.json").initial_fingerprint
            != task["fingerprint"]
        ):
            raise ValueError("Frozen task input changed during execution")

    def measure(self, task: dict, policy: dict, role: str, reserve_runs=0) -> Measurement:
        allowed = set(self.ids)
        if set(policy) != {stage.value for stage in Stage} or any(
            len(set(ids)) != len(ids) or set(ids) - allowed for ids in policy.values()
        ):
            raise ValueError("Invalid phase policy")
        if any(ids != [id_ for id_ in self.ids if id_ in ids] for ids in policy.values()):
            raise ValueError("Phase policies must preserve the configured guide order")
        if task["split"] == "holdout" and not self.state.get("policy_frozen_sha256"):
            raise ValueError("Holdout remains closed until the policy file is frozen")
        key = policy_key(task["id"], policy)
        if key in self.state["measurements"] and self.state["measurements"][key].get(
            "complete", True
        ):
            entry = self.state["measurements"][key]
            if role not in entry["roles"]:
                entry["roles"].append(role)
                self.save()
            return Measurement(**entry["measurement"])
        entry = {
            "key": key,
            "task": task["id"],
            "split": task["split"],
            "policy": policy,
            "roles": [role],
            "measurement": None,
        }
        trial_ids = []
        results = []
        try:
            for repeat in range(self.spec.repeats):
                trial_id = f"{key}-{repeat + 1:02d}"
                existing = next(
                    (trial for trial in self.state["trials"] if trial["id"] == trial_id), None
                )
                if existing:
                    if not existing.get("result") or not existing["result"]["usage_complete"]:
                        self.state["stop_reason"] = "unknown_usage"
                        raise BudgetExhausted("An existing uncertain trial will not be replayed")
                    trial_ids.append(trial_id)
                    results.append(existing["result"])
                    continue
                self.capacity(reserve_runs)
                self.verify_source(task)
                trial = {
                    "id": trial_id,
                    "task": task["id"],
                    "split": task["split"],
                    "measurement": key,
                    "repeat": repeat + 1,
                    "status": "reserved",
                    "reserved_usd": self.reservation,
                }
                self.state["trials"].append(trial)
                self.save()  # Reserve before any paid request, including crash cases.
                actual = tuple(
                    skill.model_copy(
                        update={
                            "stages": tuple(
                                stage for stage in Stage if skill.id in policy[stage.value]
                            )
                        }
                    )
                    for skill in self.skills
                )
                selected = tuple(skill.id for skill in actual if skill.stages)
                condition = Condition(id=key, policy="scoped", skill_ids=selected)
                result = self.evaluator(
                    self.root / "inputs" / task["id"] / "task.json",
                    self.settings,
                    self.root / "runs" / trial_id,
                    max_requests=self.spec.limits.per_run_calls,
                    per_phase_requests=self.spec.limits.per_phase_calls,
                    skills=actual,
                    condition=condition,
                    image_id=self.plan["image_id"],
                )
                trial["result"], trial["status"] = result, "recorded"
                trial_ids.append(trial_id)
                results.append(result)
                self.save()
                print(
                    f"{role} {task['id']} {repeat + 1}/{self.spec.repeats}: {result['status']}",
                    flush=True,
                )
                if not result["usage_complete"]:
                    self.state["stop_reason"] = "unknown_usage"
                    raise BudgetExhausted(
                        "Unknown usage stops additional calls; full reservation retained"
                    )
        except BaseException:
            measurement = self.summarize(results, trial_ids)
            entry["measurement"] = measurement.__dict__
            entry["complete"] = False
            self.state["measurements"][key] = entry
            self.save()
            raise
        measurement = self.summarize(results, trial_ids)
        entry["measurement"], entry["complete"] = measurement.__dict__, True
        self.state["measurements"][key] = entry
        self.save()
        return measurement

    def summarize(self, results, ids):
        passed = sum(
            self.valid_grade(result) and result["status"] == "passed" for result in results
        )
        failed = sum(
            self.valid_grade(result) and result["status"] == "failed" for result in results
        )
        return Measurement(passed, failed, self.spec.repeats - passed - failed, tuple(ids))

    @staticmethod
    def valid_grade(result):
        grade = result.get("grading")
        return (
            isinstance(grade, dict)
            and grade.get("status") in ("passed", "failed")
            and type(grade.get("tests")) is int
            and grade["tests"] > 0
            and result["status"] == grade["status"]
        )

    def relevant_policy(self, task):
        words = set(re.findall(r"[a-z]{4,}", task["instruction"].lower()))
        ranked = sorted(
            self.skills,
            key=lambda skill: (
                -len(words & set(re.findall(r"[a-z]{4,}", skill.text.lower()))),
                skill.id,
            ),
        )
        selected = {skill.id for skill in ranked[: min(2, len(ranked))]}
        return full_policy(tuple(id_ for id_ in self.ids if id_ in selected))

    def seed_hint(self, task):
        prior = self.plan.get("prior")
        if not prior or prior["tasks"].get(task["id"]) != task["fingerprint"]:
            return None
        candidates = [
            (value["passed"], key.removeprefix("single-"))
            for key, value in prior["conditions"].items()
            if key.startswith("single-")
            and value["valid_final_grades"] >= 3
            and value["passed"] * 3 <= value["valid_final_grades"]
        ]
        return min(candidates)[1] if candidates else None

    def diagnose_task(self, task):
        n = self.spec.repeats
        # Keep enough trial quota for the generated policy, manual scope and
        # relevance comparisons. Budget shortages become explicit partial reports.
        holdout_reserve = (
            n * 3 * sum(item["split"] == "holdout" for item in self.plan["tasks"])
            if self.spec.validate_holdout
            else 0
        )
        validation_reserve = n * 3 + holdout_reserve
        baseline = self.measure(task, full_policy(()), "baseline", validation_reserve)
        all_result = self.measure(task, full_policy(self.ids), "all", validation_reserve)
        diagnosis = {
            "task": task["id"],
            "baseline": baseline.record(),
            "all": all_result.record(),
            "classification": "not_reproduced",
            "suspects": [],
            "notes": [],
        }
        self.state["diagnoses"][task["id"]] = diagnosis
        self.save()
        if baseline.decision != "good":
            diagnosis["classification"] = "baseline_unreliable"
            diagnosis["notes"].append(
                "No skill attribution when the no-guide control is unreliable."
            )
            self.save()
            return
        hint = self.seed_hint(task)
        initial = self.ids
        if hint:
            confirmed = self.measure(
                task, full_policy((hint,)), "fresh_prior_confirmation", validation_reserve
            )
            diagnosis["prior_confirmation"] = {"skill": hint, **confirmed.record()}
            if confirmed.decision == "bad":
                initial = (hint,)
        initial_result = self.measure(
            task, full_policy(initial), "starting_set", validation_reserve
        )
        if initial_result.decision == "bad":
            reduced = reduce_combination(
                initial,
                lambda subset: self.measure(
                    task, full_policy(subset), "reduction", validation_reserve
                ),
                self.spec.limits.max_subset_evaluations,
            )
            suspects = tuple(reduced["skills"])
            diagnosis["reduction"] = reduced
            diagnosis["suspects"] = list(suspects)
            if len(suspects) == 1:
                diagnosis["classification"] = "single_skill_regression"
            else:
                try:
                    singles = [
                        self.measure(
                            task,
                            full_policy((id_,)),
                            "interaction_single_control",
                            validation_reserve,
                        )
                        for id_ in suspects
                    ]
                    diagnosis["classification"] = (
                        "combination_candidate"
                        if all(value.decision == "good" for value in singles)
                        else "mixture_with_individual_harm_or_unknown"
                    )
                except BudgetExhausted:
                    diagnosis["classification"] = "mixture_regression_unclassified"
                    diagnosis["notes"].append(
                        "Insufficient remaining diagnosis quota for every single control; interaction remains unproven."
                    )
        elif initial_result.decision == "unknown":
            diagnosis["classification"] = "inconclusive"
        self.save()
        suspects = tuple(diagnosis["suspects"])
        candidates = {
            "generated": policy_from_suspects(self.ids, self.declared, suspects)
            if suspects
            else {
                stage.value: [skill.id for skill in self.skills if stage in skill.stages]
                for stage in Stage
            },
            "manual_scoped": {
                stage.value: [skill.id for skill in self.skills if stage in skill.stages]
                for stage in Stage
            },
            "relevance": self.relevant_policy(task),
        }
        if suspects:
            candidates["remove_suspects"] = full_policy(
                tuple(id_ for id_ in self.ids if id_ not in suspects)
            )
        scored = []
        for name, policy in candidates.items():
            try:
                result = self.measure(task, policy, name, holdout_reserve)
            except BudgetExhausted:
                diagnosis["notes"].append(
                    f"Policy comparison {name} was not completed within quota."
                )
                break
            scored.append({"name": name, "policy": policy, "measurement": result.record()})
            diagnosis["policy_comparisons"] = list(scored)
            self.save()
        diagnosis["policy_comparisons"] = scored
        eligible = [
            item
            for item in scored
            if item["measurement"]["unresolved"] == 0
            and item["measurement"]["passed"] >= baseline.passed
            and item["measurement"]["passed"] >= all_result.passed
        ]
        # Prefer equal/better observed successes, then retain more guide-phase
        # slots. This is explicit selection, not a learned optimal policy.
        eligible.sort(
            key=lambda item: (
                -item["measurement"]["passed"],
                -sum(map(len, item["policy"].values())),
                item["name"],
            )
        )
        if eligible:
            chosen = eligible[0]
            diagnosis["selected_policy"] = chosen
            diagnosis["observed_improvement_over_all"] = (
                chosen["measurement"]["passed"] - all_result.passed
            )
        self.save()

    def freeze_policy(self):
        selected = [
            value for value in self.state["diagnoses"].values() if value.get("selected_policy")
        ]
        if not selected:
            self.state["policy"] = {"status": "unvalidated", "phases": {}, "holdout_tested": False}
            self.save()
            return False
        # One transferable policy must be chosen before seeing any holdout.
        choice = sorted(
            selected,
            key=lambda item: (-item["selected_policy"]["measurement"]["passed"], item["task"]),
        )[0]
        value = {
            "schema_version": 1,
            "status": "selected_on_discovery",
            "source_task": choice["task"],
            "method": choice["selected_policy"]["name"],
            "phases": choice["selected_policy"]["policy"],
            "basis": choice["classification"],
            "validation_scope": "discovery only; small samples; not an optimal or generally validated policy",
        }
        write_json(self.root / "policy.json", value)
        self.state["policy_frozen_sha256"] = hashlib.sha256(
            (self.root / "policy.json").read_bytes()
        ).hexdigest()
        self.state["policy"] = value
        self.save()
        return True

    def execute(self):
        with workflow_lock(self.root):
            self.state = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
            return self._execute()

    def _execute(self):
        if self.state["status"] == "completed":
            return self.state
        for trial in self.state["trials"]:
            if trial["status"] != "reserved":
                continue
            path = self.root / "runs" / trial["id"] / "run.json"
            if path.exists():
                result = json.loads(path.read_text(encoding="utf-8"))
                if (
                    result.get("source_sha256") == self.plan["source_sha256"]
                    and result.get("condition") == trial["measurement"]
                    and result.get("usage_complete")
                ):
                    trial["result"], trial["status"] = result, "recorded"
                    self.save()
        if any(trial["status"] == "reserved" for trial in self.state["trials"]):
            self.state["status"] = "unknown_usage_stopped"
            self.state["stop_reason"] = (
                "A previously reserved trial lacks a durable result. It will not be replayed."
            )
            self.save()
            return self.state
        if (
            self.state["status"] == "unknown_usage_stopped"
            or self.state.get("stop_reason") == "unknown_usage"
        ):
            return self.state
        if self.settings is None:
            raise ValueError("Actual execution needs model settings")
        actual_image = (
            preflight(self.settings.docker, self.plan["image_id"])
            if self.plan["image_id"]
            else preflight(self.settings.docker)
        )
        if self.plan["image_id"] is None and not self.state["trials"]:
            self.plan["image_id"] = actual_image
            write_json(self.root / "plan.json", self.plan)
            self.state["plan_sha256"] = hashlib.sha256(
                (self.root / "plan.json").read_bytes()
            ).hexdigest()
        if actual_image != self.plan["image_id"]:
            raise ValueError("Sandbox image changed after execution freeze")
        self.state["status"] = "running"
        self.save()
        try:
            for task in self.plan["tasks"]:
                if task["split"] == "discovery":
                    self.diagnose_task(task)
            frozen = self.freeze_policy()
            if frozen and self.spec.validate_holdout:
                for task in self.plan["tasks"]:
                    if task["split"] != "holdout":
                        continue
                    if (
                        hashlib.sha256((self.root / "policy.json").read_bytes()).hexdigest()
                        != self.state["policy_frozen_sha256"]
                    ):
                        raise ValueError("Frozen policy changed before holdout validation")
                    self.state["holdout_opened"] = True
                    self.save()
                    for name, policy in (
                        ("holdout_baseline", full_policy(())),
                        ("holdout_all", full_policy(self.ids)),
                        ("holdout_selected", self.state["policy"]["phases"]),
                    ):
                        self.measure(task, policy, name)
                validation = {
                    "policy_sha256": self.state["policy_frozen_sha256"],
                    "task_results": [
                        entry
                        for entry in self.state["measurements"].values()
                        if entry["split"] == "holdout"
                    ],
                    "note": "Policy remained fixed throughout holdout; these scores never tune the policy.",
                }
                write_json(self.root / "policy-validation.json", validation)
                self.state["holdout_validation"] = validation
            self.state["status"] = "completed"
        except BudgetExhausted as error:
            self.state["status"] = (
                "unknown_usage_stopped"
                if self.state.get("stop_reason") == "unknown_usage"
                else "budget_exhausted"
            )
            self.state["stop_reason"] = str(error)
        except BaseException:
            self.state["status"] = "interrupted"
            self.save()
            raise
        self.save()
        return self.state


def prepare(
    config: Path,
    output: Path,
    settings: Settings | None,
    plan_only=False,
    resume=False,
    evaluator=run_agent,
):
    spec, plan, payloads = load_repository_config(config)
    if resume:
        workflow = DiagnosisWorkflow(output, settings, evaluator)
        if (
            plan["input_sha256"] != workflow.plan["input_sha256"]
            or plan["source_sha256"] != workflow.plan["source_sha256"]
        ):
            raise ValueError("Frozen input or execution source changed; create a separate study")
        return workflow
    image = None if plan_only else preflight(settings.docker)
    output.mkdir(parents=True, exist_ok=False)
    plan["image_id"] = image
    write_json(output / "plan.json", plan)
    freeze_repository_inputs(output / "inputs", payloads)
    for task in plan["tasks"]:
        if (
            Workspace(output / "inputs" / task["id"] / "task.json").initial_fingerprint
            != task["fingerprint"]
        ):
            raise ValueError("Frozen task fingerprint changed")
    write_json(
        output / "state.json",
        {
            "status": "planned" if plan_only else "ready",
            "trials": [],
            "measurements": {},
            "diagnoses": {},
            "holdout_opened": False,
            "plan_sha256": hashlib.sha256((output / "plan.json").read_bytes()).hexdigest(),
        },
    )
    return DiagnosisWorkflow(output, settings, evaluator)
