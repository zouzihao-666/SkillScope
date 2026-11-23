"""Audit and export the completed fixed-cap follow-up, with portable hashes."""

import argparse
import gzip
import hashlib
import json
import re
import subprocess
from pathlib import Path

from dotenv import dotenv_values

from skillscope.batch import source_fingerprint, write_json
from skillscope.loader import digest

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("study", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    study, output = arguments.study, arguments.output
    status = json.loads((study / "study.json").read_text(encoding="utf-8"))
    manifest = json.loads((study / "manifest.json").read_text(encoding="utf-8"))
    if status["status"] != "completed" or status["completed"] != 40:
        raise ValueError("Expected the complete preregistered 40-run study")
    if source_fingerprint() != manifest["source_sha256"]:
        raise ValueError("Execution source changed before audit")
    if (
        digest((ROOT / "scripts/budget_study.py").read_text(encoding="utf-8"))
        != manifest["study_script_sha256"]
    ):
        raise ValueError("Study script changed before audit")
    rows = [
        json.loads(line)
        for line in (study / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    jobs = {job["id"]: job for job in manifest["plan"]["runs"]}
    if len(rows) != len(jobs) or {row["job"]["id"] for row in rows} != set(jobs):
        raise ValueError("Missing or duplicate study records")
    rows.sort(key=lambda row: row["job"]["id"])
    records = []
    for row in rows:
        if row["job"] != jobs[row["job"]["id"]]:
            raise ValueError("Run differs from frozen plan")
        directory = study / "runs" / row["job"]["id"]
        trace = [
            json.loads(line)
            for line in (directory / "trace.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        code = directory / "candidate.py"
        candidate = code.read_text(encoding="utf-8") if code.exists() else None
        records.append(
            {
                "run": row,
                "trace": trace,
                "candidate": candidate,
                "candidate_sha256": digest(candidate) if candidate is not None else None,
            }
        )
    raw = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
    ).encode()
    key = dotenv_values(ROOT / ".env").get("DEEPSEEK_API_KEY")
    if key and key.encode() in raw:
        raise ValueError("Credential found; export aborted")
    if re.search(
        rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})", raw
    ):
        raise ValueError("Credential-like content found; export aborted")
    output.mkdir(parents=True, exist_ok=False)
    for name in ("manifest.json", "study.json", "results.jsonl", "report.json", "report.md"):
        (output / name).write_bytes((study / name).read_text(encoding="utf-8").encode("utf-8"))
    with (output / "raw-runs.jsonl.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as archive:
            archive.write(raw)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    write_json(
        output / "provenance.json",
        {
            "preregistered_execution_commit": commit,
            "raw_records": len(records),
            "raw_jsonl_sha256": hashlib.sha256(raw).hexdigest(),
            "text_encoding": "UTF-8/LF; candidate hashes use normalized candidate text",
            "source_sha256": manifest["source_sha256"],
            "study_script_sha256": manifest["study_script_sha256"],
            "not_in_archive": ["API keys", "HTTP authentication headers", "environment files"],
        },
    )
    path = output / "provenance.json"
    path.write_bytes(path.read_text(encoding="utf-8").encode("utf-8"))
    checksums = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.iterdir())
        if path.is_file()
    }
    write_json(output / "checksums.json", checksums)
    path = output / "checksums.json"
    path.write_bytes(path.read_text(encoding="utf-8").encode("utf-8"))
    print(f"Exported {len(records)} audited records to {output}")


if __name__ == "__main__":
    main()
