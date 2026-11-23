"""Publish all three engineering attempts, without pooling changed protocol versions."""

import gzip
import hashlib
import json
import re
import subprocess
from pathlib import Path

from dotenv import dotenv_values

from skillscope.batch import write_json
from skillscope.loader import digest

ROOT = Path(__file__).resolve().parents[1]
ATTEMPTS = [
    ("v1", "bbb9ff7", "repo-agent-smoke-20261123", "parallel_tool_count_limit_in_prototype"),
    ("v2", "c49e20c", "repo-agent-smoke-v2-20261123", "model_submitted_malformed_json"),
    (
        "v3",
        "23d35bc",
        "repo-agent-smoke-v3-20261123",
        "plain_source_and_bounded_tool_error_feedback",
    ),
]


def main():
    output = ROOT / "artifacts/repo-prototype-20261123"
    payloads, summaries = [], []
    for version, commit, folder, interpretation in ATTEMPTS:
        directory = ROOT / "results" / folder
        run = json.loads((directory / "run.json").read_text(encoding="utf-8"))
        source = subprocess.run(
            ["git", "show", f"{commit}:scripts/repo_agent.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        ).stdout
        if digest(source) != run["runner_sha256"]:
            raise ValueError("Runner source does not match the preregistered commit")
        trace = [
            json.loads(line)
            for line in (directory / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        workspace = json.loads((directory / "workspace-final.json").read_text(encoding="utf-8"))
        payloads.append(
            {
                "version": version,
                "preregistered_commit": commit,
                "run": run,
                "interpretation": interpretation,
                "trace": trace,
                "workspace": workspace,
            }
        )
        summaries.append(
            {
                "version": version,
                "preregistered_commit": commit,
                "interpretation": interpretation,
                **run,
            }
        )
    if not all(row["usage_complete"] for row in summaries):
        raise ValueError("Cannot present usage as complete")
    total = {
        "calls": sum(row["calls_attempted"] for row in summaries),
        "reported_tokens": sum(row["reported_tokens"]["total_tokens"] for row in summaries),
        "estimated_usd_upper": sum(row["estimated_usd_upper"] for row in summaries),
        "max_estimated_usd": 0.25,
        "note": "Engineering attempts used different protocol versions; do not pool success rates.",
    }
    if total["estimated_usd_upper"] > 0.25:
        raise ValueError("Combined estimate exceeds the original prototype budget")
    raw = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in payloads
    ).encode()
    key = dotenv_values(ROOT / ".env").get("DEEPSEEK_API_KEY")
    if key and key.encode() in raw:
        raise ValueError("Credential found; export aborted")
    if re.search(
        rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})", raw
    ):
        raise ValueError("Credential-like content found")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "attempts.json", summaries)
    write_json(output / "totals.json", total)
    write_json(output / "workspace-v3.json", payloads[-1]["workspace"])
    with (output / "raw-attempts.jsonl.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as archive:
            archive.write(raw)
    for path in output.glob("*.json"):
        path.write_bytes(path.read_text(encoding="utf-8").encode("utf-8"))
    checksums = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.iterdir())
        if path.is_file()
    }
    write_json(output / "checksums.json", checksums)
    path = output / "checksums.json"
    path.write_bytes(path.read_text(encoding="utf-8").encode("utf-8"))
    print(
        f"Exported all 3 engineering attempts; {total['calls']} calls; {total['reported_tokens']} tokens."
    )


if __name__ == "__main__":
    main()
