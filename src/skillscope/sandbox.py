"""Trusted host scoring; model-generated Python executes only in Docker.

The grader is never mounted in the container. Each function call gets a new
container. JSON RPC supports the plain JSON values used by the starter tasks.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

IMAGE = "skillscope-sandbox:0.2.0"
FILES = Path(__file__).parent / "sandbox_files"


class SandboxError(RuntimeError):
    pass


class CandidateError(RuntimeError):
    pass


def docker_env(docker: str) -> dict:
    # Docker Desktop's credential helper must also be discoverable in a stale terminal PATH.
    env = {key: value for key, value in os.environ.items() if key.upper() != "PATH"}
    env["PATH"] = str(Path(docker).parent) + os.pathsep + os.environ.get("PATH", "")
    return env


def preflight(docker: str, image: str = IMAGE) -> str:
    try:
        info = subprocess.run(
            [docker, "info", "--format", "{{.OSType}}"],
            capture_output=True,
            timeout=15,
            env=docker_env(docker),
        )
        if info.returncode or info.stdout.strip() != b"linux":
            raise SandboxError("Docker must be running with Linux containers")
        inspected = subprocess.run(
            [docker, "image", "inspect", image, "--format", "{{.Id}}"],
            capture_output=True,
            timeout=15,
            env=docker_env(docker),
        )
        if inspected.returncode:
            raise SandboxError("Sandbox image missing; run skillscope sandbox-build first")
        return inspected.stdout.decode().strip()
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SandboxError("Docker preflight failed") from error


def build_image(docker: str) -> None:
    # Only trusted Dockerfile/worker files enter this build context, never the project or .env.
    try:
        result = subprocess.run(
            [docker, "build", "-t", IMAGE, str(FILES)], timeout=600, env=docker_env(docker)
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SandboxError("Sandbox image build could not complete") from error
    if result.returncode:
        raise SandboxError("Sandbox image build failed")


def bounded_process(command: list[str], payload: bytes, timeout: float) -> tuple[int, bytes, bytes]:
    """Bound both stdout and stderr so printing loops cannot exhaust host memory."""
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    buffers = [bytearray(), bytearray()]
    exceeded = threading.Event()

    def read(stream, buffer):
        while chunk := stream.read(4096):
            if len(buffer) + len(chunk) > 65536:
                exceeded.set()
                process.kill()
                break
            buffer.extend(chunk)

    threads = [
        threading.Thread(target=read, args=(stream, buffer), daemon=True)
        for stream, buffer in zip((process.stdout, process.stderr), buffers, strict=True)
    ]
    for thread in threads:
        thread.start()
    try:
        process.stdin.write(payload)
        process.stdin.close()
        process.wait(timeout=timeout)
    except (subprocess.TimeoutExpired, BrokenPipeError):
        process.kill()
        process.wait(timeout=5)
        raise
    finally:
        for thread in threads:
            thread.join(timeout=2)
    if exceeded.is_set():
        raise CandidateError("Candidate exceeded the output limit")
    return process.returncode, bytes(buffers[0]), bytes(buffers[1])


def invoke(function: str, args: tuple):
    """Called by a trusted proxy imported by the independent pytest grader."""
    docker = os.environ["SKILLSCOPE_RPC_DOCKER"]
    image = os.environ["SKILLSCOPE_RPC_IMAGE"]
    candidate_dir = os.environ["SKILLSCOPE_RPC_CANDIDATE"]
    events = Path(os.environ["SKILLSCOPE_RPC_EVENTS"])
    prior_events = events.read_text(encoding="utf-8").splitlines() if events.exists() else []
    if len(prior_events) >= 32:
        raise CandidateError("Grader invocation budget exhausted")
    payload = json.dumps({"function": function, "args": args}, allow_nan=False).encode()
    if len(payload) > 65536:
        raise CandidateError("Input exceeds JSON RPC limit")
    name = f"skillscope-{uuid.uuid4().hex}"
    command = [
        docker,
        "run",
        "--rm",
        "-i",
        "--name",
        name,
        "--label",
        "skillscope.group=" + os.environ["SKILLSCOPE_RPC_GROUP"],
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "32",
        "--memory",
        "128m",
        "--cpus",
        "1",
        "--log-driver",
        "none",
        "--user",
        "65534:65534",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=16m",
        "--mount",
        f"type=bind,source={Path(candidate_dir) / 'candidate.py'},target=/candidate/candidate.py,readonly",
        image,
    ]
    status = "ok"
    try:
        code, stdout, _ = bounded_process(command, payload, timeout=8)
        if code in (125, 126, 127):
            status = "infrastructure_error"
            raise SandboxError("Docker could not start the candidate worker")
        if code:
            raise CandidateError(f"Candidate worker exited with code {code}")
        try:
            response = json.loads(stdout)
        except (ValueError, UnicodeError) as error:
            raise CandidateError("Candidate returned invalid JSON RPC output") from error
        if not isinstance(response, dict):
            raise CandidateError("Candidate returned a malformed RPC response")
        if "exception" in response:
            allowed = {
                "ValueError": ValueError,
                "TypeError": TypeError,
                "KeyError": KeyError,
                "IndexError": IndexError,
                "ZeroDivisionError": ZeroDivisionError,
                "RuntimeError": RuntimeError,
            }
            raise allowed.get(response["exception"], CandidateError)(
                f"Remote candidate exception: {response['exception']}"
            )
        if not all(key in response for key in ("result", "args_after", "result_aliases")):
            raise CandidateError("Incomplete RPC response")
        # Preserve mutations and top-level result identity for the starter task tests.
        for original, after in zip(args, response["args_after"], strict=True):
            if isinstance(original, list):
                original[:] = after
            elif isinstance(original, dict):
                original.clear()
                original.update(after)
        aliases = response["result_aliases"]
        return args[aliases[0]] if aliases else response["result"]
    except subprocess.TimeoutExpired as error:
        status = "timeout"
        raise CandidateError("Candidate container timed out") from error
    except OSError as error:
        status = "infrastructure_error"
        raise SandboxError("Docker CLI could not be launched") from error
    finally:
        # Also remove a daemon-side container after a client timeout/kill.
        try:
            subprocess.run(
                [docker, "rm", "-f", name], capture_output=True, timeout=10, env=docker_env(docker)
            )
        except (OSError, subprocess.TimeoutExpired):
            status = "infrastructure_error"
        with events.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"status": status}) + "\n")


def grade(candidate: str, grader: str, docker: str, image: str, output: Path) -> dict:
    """Only trusted grader/proxy code runs on the host; the candidate never does."""
    with tempfile.TemporaryDirectory(prefix="skillscope-code-") as code_dir:
        with tempfile.TemporaryDirectory(prefix="skillscope-grader-") as test_dir:
            code_root, test_root = Path(code_dir), Path(test_dir)
            (code_root / "candidate.py").write_text(candidate, encoding="utf-8")
            if os.name != "nt":
                (code_root / "candidate.py").chmod(0o444)
            (test_root / "test_subject.py").write_text(grader, encoding="utf-8")
            (test_root / "candidate.py").write_text(
                "from skillscope.sandbox import invoke\n"
                "def clamp(value, lower, upper):\n"
                "    return invoke('clamp', (value, lower, upper))\n"
                "def deduplicate(items):\n"
                "    return invoke('deduplicate', (items,))\n",
                encoding="utf-8",
            )
            (test_root / "conftest.py").write_text(
                "import sys\nfrom pathlib import Path\n"
                "sys.path.insert(0, str(Path(__file__).parent))\n",
                encoding="utf-8",
            )
            events_file = test_root / "events.jsonl"
            group = uuid.uuid4().hex
            env = {
                **docker_env(docker),
                "PYTHONUTF8": "1",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "SKILLSCOPE_RPC_DOCKER": docker,
                "SKILLSCOPE_RPC_IMAGE": image,
                "SKILLSCOPE_RPC_CANDIDATE": str(code_root),
                "SKILLSCOPE_RPC_EVENTS": str(events_file),
                "SKILLSCOPE_RPC_GROUP": group,
            }
            env.pop("PYTEST_ADDOPTS", None)
            command = [
                sys.executable,
                "-I",
                "-m",
                "pytest",
                "-q",
                "test_subject.py",
                "-p",
                "no:cacheprovider",
                "--junitxml=report.xml",
            ]
            try:
                result = subprocess.run(
                    command, cwd=test_root, env=env, capture_output=True, timeout=180
                )
            except subprocess.TimeoutExpired:
                return {"status": "timeout", "passed": None, "tests": None}
            finally:
                cleanup_group(docker, group)
            (output / "grader.log").write_bytes(result.stdout + result.stderr)
            records = (
                [json.loads(line) for line in events_file.read_text().splitlines()]
                if events_file.exists()
                else []
            )
            if any(record["status"] == "infrastructure_error" for record in records):
                return {"status": "infrastructure_error", "passed": None, "tests": None}
            if any(record["status"] == "timeout" for record in records):
                return {"status": "timeout", "passed": None, "tests": None}
            report = test_root / "report.xml"
            if not report.exists():
                return {"status": "infrastructure_error", "passed": None, "tests": None}
            (output / "report.xml").write_bytes(report.read_bytes())
            suites = list(ET.parse(report).getroot().iter("testsuite"))
            tests = sum(int(suite.get("tests", 0)) for suite in suites)
            failures = sum(
                int(suite.get("failures", 0)) + int(suite.get("errors", 0)) for suite in suites
            )
            if not records or not tests or result.returncode not in (0, 1):
                return {"status": "infrastructure_error", "passed": None, "tests": tests}
            passed = result.returncode == 0 and failures == 0
            return {
                "status": "passed" if passed else "failed",
                "passed": passed,
                "tests": tests,
                "failures": failures,
                "container_calls": len(records),
            }


def cleanup_group(docker: str, group: str) -> None:
    result = subprocess.run(
        [docker, "ps", "-aq", "--filter", f"label=skillscope.group={group}"],
        capture_output=True,
        timeout=15,
        env=docker_env(docker),
    )
    if result.returncode:
        raise SandboxError("Could not verify candidate container cleanup")
    ids = result.stdout.decode().split()
    if ids:
        removed = subprocess.run(
            [docker, "rm", "-f", *ids], capture_output=True, timeout=15, env=docker_env(docker)
        )
        if removed.returncode:
            raise SandboxError("Could not clean up candidate containers")
