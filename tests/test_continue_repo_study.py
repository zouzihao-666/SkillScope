from scripts import continue_repo_study as study


def test_failed_patch_with_valid_grade_opens_gate_but_unknown_usage_does_not(monkeypatch):
    monkeypatch.setattr("scripts.repo_calibration.preflight", lambda _: "test-image")
    plan = study.make_plan("unused")
    assert len(plan["runs"]) == 5
    assert [job["cohort"] for job in plan["runs"]] == ["engineering"] + ["calibration"] * 4
    assert all(job["task"] != "dotenv-bom" for job in plan["runs"])
    failed_patch = {
        "status": "failed",
        "grading": {"status": "failed", "tests": 9},
        "usage_complete": True,
        "calls_attempted": 10,
        "estimated_usd_upper": 0.01,
    }
    assert study.final_grade_available(failed_patch)
    assert study.can_start(plan, [{"result": failed_patch}]) is None
    assert (
        study.can_start(plan, [{"result": {**failed_patch, "usage_complete": False}}])
        == "unknown_usage_stopped"
    )
    assert (
        study.can_start(plan, [{"result": {**failed_patch, "grading": None}}])
        == "pilot_gate_stopped"
    )
    assert (
        study.can_start(plan, [{"result": {**failed_patch, "estimated_usd_upper": 1.4}}])
        == "budget_stopped"
    )
