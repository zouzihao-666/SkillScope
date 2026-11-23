import json

from typer.testing import CliRunner

from skillscope.cli import app

runner = CliRunner()


def test_check_then_plan_and_preview(config, tmp_path):
    assert runner.invoke(app, ["check", "--config", str(config)]).exit_code == 0
    output = tmp_path / "results" / "plan.json"
    arguments = ["plan", "--config", str(config), "--output", str(output)]
    result = runner.invoke(app, arguments)
    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["run_count"] == 15
    original = output.read_bytes()
    assert runner.invoke(app, arguments).exit_code == 1
    assert output.read_bytes() == original
    preview = runner.invoke(
        app, ["preview", "--config", str(config), "--condition", "scoped", "--stage", "implement"]
    )
    assert preview.exit_code == 0, preview.output
    assert "minimal-fix" in json.loads(preview.output)[0]["content"]
    assert "root-cause" not in json.loads(preview.output)[0]["content"]


def test_invalid_input_does_not_create_plan(config, tmp_path):
    output = tmp_path / "invalid.json"
    result = runner.invoke(
        app, ["plan", "--config", str(config), "--repeats", "0", "--output", str(output)]
    )
    assert result.exit_code != 0
    assert not output.exists()


def test_missing_file_and_unknown_condition_are_reported(config, tmp_path):
    assert runner.invoke(app, ["check", "--config", str(tmp_path / "missing.json")]).exit_code == 1
    result = runner.invoke(app, ["preview", "--config", str(config), "--condition", "typo"])
    assert result.exit_code == 1
    assert "unknown condition" in result.output
