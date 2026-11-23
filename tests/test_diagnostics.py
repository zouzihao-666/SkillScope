import pytest

from skillscope.diagnostics import Measurement, policy_from_suspects, reduce_combination


def test_reduction_finds_single_harm_and_checks_removing_the_last_skill():
    calls = []

    def evaluate(ids):
        calls.append(ids)
        return Measurement(0, 3, 0) if "bad" in ids else Measurement(3, 0, 0)

    result = reduce_combination(("a", "bad", "c", "d"), evaluate)
    assert result["skills"] == ["bad"] and result["one_removal_minimal"]
    assert () in calls and len(calls) == len(set(calls))


def test_reduction_finds_interaction_without_claiming_global_minimum():
    def evaluate(ids):
        return Measurement(1, 2, 0) if {"a", "b"} <= set(ids) else Measurement(3, 0, 0)

    result = reduce_combination(("a", "b", "c", "d"), evaluate)
    assert set(result["skills"]) == {"a", "b"}
    assert result["status"] == "reduced" and result["one_removal_minimal"]


def test_unknown_and_budget_do_not_become_false_conflict_certificates():
    result = reduce_combination(
        ("a", "b"), lambda ids: Measurement(0, 3, 0) if len(ids) == 2 else Measurement(0, 0, 3)
    )
    assert result["skills"] == ["a", "b"] and not result["one_removal_minimal"]
    limited = reduce_combination(("a", "b"), lambda _: Measurement(0, 3, 0), max_evaluations=1)
    assert limited["status"] == "budget_exhausted" and limited["bad_subset_reproduced"]
    assert len(limited["evaluations"]) == 1
    unknown = reduce_combination(("a",), lambda _: Measurement(0, 1, 2))
    assert unknown["status"] == "unknown"


def test_baseline_failure_and_non_reproduction_are_preserved():
    assert reduce_combination((), lambda _: Measurement(0, 3, 0))["status"] == "baseline_failure"
    assert reduce_combination(("a",), lambda _: Measurement(3, 0, 0))["status"] == "not_reproduced"
    with pytest.raises(ValueError):
        Measurement(-1, 3, 0)


def test_policy_only_restricts_suspects_and_preserves_other_guides():
    value = policy_from_suspects(
        ("good", "bad"), {"good": ("implement",), "bad": ("verify",)}, ("bad",)
    )
    assert value == {"investigate": ["good"], "implement": ["good"], "verify": ["good", "bad"]}
    with pytest.raises(ValueError):
        policy_from_suspects(("a",), {"a": ("verify",)}, ("unknown",))
