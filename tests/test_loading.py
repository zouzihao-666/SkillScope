import json

import pytest

from skillscope.loader import load_experiment


def rewrite(config, modify):
    data = json.loads(config.read_text(encoding="utf-8"))
    modify(data)
    config.write_text(json.dumps(data), encoding="utf-8")


def test_content_and_scope_changes_invalidate_fingerprint(config, experiment):
    skill = config.parent / "skills/root-cause.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\nMore instructions.", encoding="utf-8")
    changed = load_experiment(config)
    assert changed.sha256 != experiment.sha256
    assert changed.skills[0].sha256 != experiment.skills[0].sha256
    rewrite(config, lambda data: data["skills"][0].update(stages=["verify"]))
    assert load_experiment(config).sha256 != changed.sha256


def test_grader_changes_are_recorded_without_exposing_grader_text(config, experiment):
    grader = config.parent / "graders/test_clamp.py"
    grader.write_text(grader.read_text(encoding="utf-8") + "\n# hidden-canary\n", encoding="utf-8")
    changed = load_experiment(config)
    assert changed.sha256 != experiment.sha256
    assert changed.tasks[0].grader_sha256 != experiment.tasks[0].grader_sha256
    assert "hidden-canary" not in changed.model_dump_json()


@pytest.mark.parametrize("kind", ["skills", "tasks"])
def test_duplicate_ids_are_rejected(config, kind):
    rewrite(config, lambda data: data[kind].append(data[kind][0]))
    with pytest.raises(ValueError, match="duplicate"):
        load_experiment(config)


def test_path_escape_is_rejected_even_if_file_exists(config):
    (config.parent.parent / "private.txt").write_text("private", encoding="utf-8")
    rewrite(config, lambda data: data["skills"][0].update(file="../private.txt"))
    with pytest.raises(ValueError, match="inside experiment"):
        load_experiment(config)


def test_empty_skill_is_rejected(config):
    (config.parent / "skills/root-cause.md").write_text(" \n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_experiment(config)


def test_unknown_stage_is_rejected(config):
    rewrite(config, lambda data: data["skills"][0].update(stages=["investigatee"]))
    with pytest.raises(ValueError):
        load_experiment(config)


def test_unknown_config_keys_are_rejected(config):
    rewrite(config, lambda data: data.update(repaets=3))
    with pytest.raises(ValueError):
        load_experiment(config)


def test_key_order_does_not_change_fingerprint(config, experiment):
    data = json.loads(config.read_text(encoding="utf-8"))
    config.write_text(json.dumps(data, sort_keys=True), encoding="utf-8")
    assert load_experiment(config).sha256 == experiment.sha256
