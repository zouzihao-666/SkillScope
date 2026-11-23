"""Opt-in real Docker tests. They never call the model API."""

import os
import subprocess
import uuid

import pytest

from skillscope.sandbox import CandidateError, grade, invoke, preflight

pytestmark = pytest.mark.skipif(
    not os.environ.get("SKILLSCOPE_TEST_DOCKER"),
    reason="set SKILLSCOPE_TEST_DOCKER to opt into Docker tests",
)


@pytest.mark.parametrize(
    "code,expected",
    [
        (
            "def clamp(value, lower, upper):\n    if lower > upper: raise ValueError()\n"
            "    return min(upper, max(lower, value))\n",
            "passed",
        ),
        ("def clamp(value, lower, upper):\n    return min(lower, max(value, upper))\n", "failed"),
    ],
)
def test_real_container_accepts_correct_code_and_rejects_broken_code(
    config, tmp_path, code, expected
):
    docker = os.environ["SKILLSCOPE_TEST_DOCKER"]
    image = preflight(docker)
    grader = (config.parent / "graders/test_clamp.py").read_text(encoding="utf-8")
    result = grade(code, grader, docker, image, tmp_path)
    assert result["status"] == expected
    assert result["tests"] == 9


@pytest.mark.parametrize(
    "code,expected",
    [
        (
            "def deduplicate(items):\n    out = []\n    for item in items:\n"
            "        if item not in out: out.append(item)\n    return out\n",
            "passed",
        ),
        ("def deduplicate(items):\n    return items\n", "failed"),
        ("def deduplicate(items):\n    items.clear()\n    return []\n", "failed"),
    ],
)
def test_rpc_preserves_mutation_and_identity_checks(config, tmp_path, code, expected):
    docker = os.environ["SKILLSCOPE_TEST_DOCKER"]
    grader = (config.parent / "graders/test_deduplicate.py").read_text(encoding="utf-8")
    result = grade(code, grader, docker, preflight(docker), tmp_path)
    assert result["status"] == expected
    assert result["tests"] == 5


def rpc_environment(tmp_path, monkeypatch, code):
    docker = os.environ["SKILLSCOPE_TEST_DOCKER"]
    (tmp_path / "candidate.py").write_text(code, encoding="utf-8")
    group = uuid.uuid4().hex
    for key, value in {
        "DOCKER": docker,
        "IMAGE": preflight(docker),
        "CANDIDATE": str(tmp_path),
        "EVENTS": str(tmp_path / "events.jsonl"),
        "GROUP": group,
    }.items():
        monkeypatch.setenv("SKILLSCOPE_RPC_" + key, value)
    return docker, group


def test_candidate_does_not_receive_host_key_and_cannot_modify_code(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "host-only-canary")
    rpc_environment(
        tmp_path,
        monkeypatch,
        "def clamp(*args):\n    import os\n    assert 'DEEPSEEK_API_KEY' not in os.environ\n"
        "    assert os.getuid() == 65534\n"
        "    try:\n        open('/candidate/candidate.py', 'w')\n"
        "    except OSError:\n        return True\n    return False\n",
    )
    assert invoke("clamp", (1, 0, 2)) is True


def test_timeout_removes_daemon_side_container(tmp_path, monkeypatch):
    docker, group = rpc_environment(
        tmp_path, monkeypatch, "def clamp(*args):\n    while True: pass\n"
    )
    with pytest.raises(CandidateError, match="timed out"):
        invoke("clamp", (1, 0, 2))
    remaining = subprocess.run(
        [docker, "ps", "-aq", "--filter", f"label=skillscope.group={group}"],
        capture_output=True,
        check=True,
    )
    assert not remaining.stdout.strip()
