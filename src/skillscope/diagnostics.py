"""Budgeted set reduction with explicit unknown outcomes, independent of any model API."""

from dataclasses import asdict, dataclass
from typing import Callable, Literal

Decision = Literal["good", "bad", "unknown"]


class BudgetExhausted(RuntimeError):
    pass


@dataclass(frozen=True)
class Measurement:
    passed: int
    failed: int
    unresolved: int
    run_ids: tuple[str, ...] = ()

    def __post_init__(self):
        if any(
            type(value) is not int or value < 0
            for value in (self.passed, self.failed, self.unresolved)
        ):
            raise ValueError("Outcome counts must be nonnegative integers")
        if self.passed + self.failed + self.unresolved < 1:
            raise ValueError("A measurement must contain an attempted trial")

    @property
    def decision(self) -> Decision:
        total = self.passed + self.failed + self.unresolved
        if self.unresolved:
            return "unknown"
        if self.passed * 3 <= total:
            return "bad"
        if self.passed * 3 >= total * 2:
            return "good"
        return "unknown"

    def record(self) -> dict:
        return {**asdict(self), "decision": self.decision}


def reduce_combination(
    skill_ids: tuple[str, ...],
    evaluate: Callable[[tuple[str, ...]], Measurement],
    max_evaluations: int = 12,
) -> dict:
    """Find a smaller reproduced bad subset; never treat missing grades as failure.

    The result is at most one-removal minimal, not globally minimum. A cached
    measurement is reused explicitly and consumes no additional oracle calls.
    """
    if len(set(skill_ids)) != len(skill_ids) or max_evaluations < 1:
        raise ValueError("Expected unique skills and a positive evaluation limit")
    current = tuple(skill_ids)
    cache: dict[tuple[str, ...], Measurement] = {}
    trace = []

    def check(subset):
        if subset not in cache:
            if len(cache) >= max_evaluations:
                raise BudgetExhausted("Subset evaluation limit reached")
            result = evaluate(subset)
            if not isinstance(result, Measurement):
                raise ValueError("Evaluator must return a Measurement")
            cache[subset] = result
            trace.append({"skills": list(subset), **result.record()})
        return cache[subset]

    reproduced = False
    try:
        first = check(current)
        if first.decision != "bad":
            return {
                "status": "not_reproduced" if first.decision == "good" else "unknown",
                "skills": list(current),
                "one_removal_minimal": False,
                "evaluations": trace,
            }
        reproduced = True
        if not current:
            return {
                "status": "baseline_failure",
                "skills": [],
                "one_removal_minimal": False,
                "evaluations": trace,
            }
        granularity = 2
        while len(current) > 1:
            size = (len(current) + granularity - 1) // granularity
            removed = False
            for offset in range(0, len(current), size):
                subset = current[:offset] + current[offset + size :]
                if check(subset).decision == "bad":
                    current = subset
                    granularity = max(2, granularity - 1)
                    removed = True
                    break
            if removed:
                continue
            if granularity >= len(current):
                break
            granularity = min(len(current), granularity * 2)
        # A final pass also checks deletion of the last remaining skill.
        while current:
            results = []
            for index in range(len(current)):
                subset = current[:index] + current[index + 1 :]
                result = check(subset)
                if result.decision == "bad":
                    current = subset
                    break
                results.append(result.decision)
            else:
                minimal = all(value == "good" for value in results)
                return {
                    "status": "reduced" if minimal else "partial_unknown",
                    "skills": list(current),
                    "one_removal_minimal": minimal,
                    "evaluations": trace,
                }
        return {
            "status": "baseline_failure",
            "skills": [],
            "one_removal_minimal": False,
            "evaluations": trace,
        }
    except BudgetExhausted:
        return {
            "status": "budget_exhausted",
            "skills": list(current),
            "bad_subset_reproduced": reproduced,
            "one_removal_minimal": False,
            "evaluations": trace,
        }


def policy_from_suspects(
    skill_ids: tuple[str, ...], declared: dict[str, tuple[str, ...]], suspects: tuple[str, ...]
) -> dict:
    """Keep other guides global and restrict suspects to their declared phases."""
    if set(suspects) - set(skill_ids) or set(skill_ids) != set(declared):
        raise ValueError("Policy identifiers do not match the guide inventory")
    stages = ("investigate", "implement", "verify")
    if any(not value or set(value) - set(stages) for value in declared.values()):
        raise ValueError("Each guide needs valid declared stages")
    return {
        stage: [id_ for id_ in skill_ids if id_ not in suspects or stage in declared[id_]]
        for stage in stages
    }
