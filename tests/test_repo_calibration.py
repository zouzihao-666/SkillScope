from scripts import repo_calibration
from skillscope.batch import estimate_cost


def test_fixed_plan_excludes_holdout_and_reserves_full_request_ceiling(monkeypatch):
    monkeypatch.setattr(repo_calibration, "preflight", lambda _: "test-image")
    plan = repo_calibration.make_plan("not-used")
    assert plan == repo_calibration.make_plan("not-used")
    assert len(plan["runs"]) == 4
    assert {(row["task"], row["repeat"]) for row in plan["runs"]} == {
        (task, repeat) for task in ("dotenv-backslash", "dotenv-comment") for repeat in (1, 2)
    }
    assert "dotenv-bom" not in plan["workspace_sha256"]
    reservation = estimate_cost(
        {"prompt_tokens": 10 * (65536 + 1024), "completion_tokens": 10 * 2048}
    )
    assert reservation * 4 <= plan["budget"]["max_estimated_usd"]
