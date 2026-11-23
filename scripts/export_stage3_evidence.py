"""Publish an audited, portable archive after a completed batch; never call a model."""

import argparse
import gzip
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from dotenv import dotenv_values

from skillscope.batch import source_fingerprint, write_json
from skillscope.loader import load_experiment
from skillscope.report import save_report

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    batch, output = arguments.batch, arguments.output
    status = json.loads((batch / "batch.json").read_text(encoding="utf-8"))
    if status["status"] != "completed":
        raise ValueError("Only complete batches may use this complete-evidence exporter")
    manifest = json.loads((batch / "manifest.json").read_text(encoding="utf-8"))
    if manifest["source_sha256"] != source_fingerprint():
        raise ValueError("Execution code changed; review provenance before publishing")
    report = save_report(batch)
    rows = [
        json.loads(line)
        for line in (batch / "results.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    order = {job["id"]: index for index, job in enumerate(manifest["plan"]["runs"])}
    rows.sort(
        key=lambda row: (
            row["job"]["phase"] == "main",
            order.get(row["job"]["id"], -1),
            row["job"]["id"],
        )
    )
    payloads = []
    token_groups = defaultdict(
        lambda: {
            "input_tokens": 0,
            "output_tokens": 0,
            "first_phase_input_tokens": [],
            "first_phase_system_characters": [],
        }
    )
    for row in rows:
        directory = batch / "runs" / row["job"]["id"]
        record = {
            "run": row,
            "trace": [
                json.loads(line)
                for line in (directory / "trace.jsonl").read_text(encoding="utf-8").splitlines()
            ],
        }
        if row["job"]["phase"] == "main":
            group = token_groups[row["job"]["condition_id"]]
            group["input_tokens"] += row["reported_tokens"]["prompt_tokens"]
            group["output_tokens"] += row["reported_tokens"]["completion_tokens"]
            for event in record["trace"]:
                if event.get("stage") != "investigate":
                    continue
                if event["type"] == "request":
                    group["first_phase_system_characters"].append(
                        len(event["messages"][0]["content"])
                    )
                elif event["type"] == "response":
                    group["first_phase_input_tokens"].append(
                        event["response"]["usage"]["prompt_tokens"]
                    )
        candidate = directory / "candidate.py"
        record["candidate"] = candidate.read_text(encoding="utf-8") if candidate.exists() else None
        record["candidate_sha256"] = (
            hashlib.sha256(record["candidate"].encode("utf-8")).hexdigest()
            if candidate.exists()
            else None
        )
        record["candidate_original_file_sha256"] = (
            hashlib.sha256(candidate.read_bytes()).hexdigest() if candidate.exists() else None
        )
        log = directory / "grader.log"
        if row["status"] != "passed" and log.exists():
            text = log.read_text(encoding="utf-8", errors="replace")
            for root in (str(ROOT), str(ROOT).replace("\\", "\\\\"), str(ROOT).replace("\\", "/")):
                text = text.replace(root, "<checkout>")
            text = re.sub(
                r"(?i)[A-Z]:\\Users\\[^\\]+\\AppData\\Local\\Temp\\skillscope-[^\\\s]+",
                "<temporary-directory>",
                text,
            )
            record["failed_grader_log_paths_redacted"] = text
        payloads.append(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    raw = "".join(payloads).encode("utf-8")
    key = dotenv_values(ROOT / ".env").get("DEEPSEEK_API_KEY")
    if key and key.encode() in raw:
        raise ValueError("Credential found in evidence; publishing aborted")
    if re.search(
        rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})", raw
    ):
        raise ValueError("Credential-like content found in evidence; review required")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "manifest.json", manifest)
    write_json(output / "batch.json", status)
    write_json(output / "report.json", report)
    write_json(output / "token-comparison.json", dict(token_groups))
    token_lines = [
        "# 字符长度与实际 token 用量",
        "",
        "主实验各组具有相同的题目与重复次数。首阶段没有前序模型交接内容，便于比较固定输入；"
        "后续阶段的输入还受生成摘要和候选代码长度影响。下表仅核对用量，不推断性能因果关系。",
        "",
        "| 配置 | 首阶段系统文本平均字符数 | 首阶段平均输入 tokens | 全阶段输入 tokens | 全阶段输出 tokens |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for condition in manifest["plan"]["conditions"]:
        name = condition["id"]
        group = token_groups[name]
        chars = group["first_phase_system_characters"]
        tokens = group["first_phase_input_tokens"]
        token_lines.append(
            f"| {name} | {sum(chars) / len(chars):.1f} | "
            f"{sum(tokens) / len(tokens):.1f} | {group['input_tokens']} | "
            f"{group['output_tokens']} |"
        )
    token_lines += ["", "字符等长不保证分词后的 token 数相同；两种无关文本也可能影响模型。", ""]
    (output / "token-comparison.md").write_text("\n".join(token_lines), encoding="utf-8")
    (output / "report.md").write_text(
        (batch / "report.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (output / "results.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    with (output / "raw-runs.jsonl.gz").open("wb") as stream:
        with gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as archive:
            archive.write(raw)
    check = ROOT / "results/stage3-corpus-check-001/corpus-check.json"
    if check.exists():
        checked = json.loads(check.read_text(encoding="utf-8"))
        if checked["experiment_sha256"] != manifest["experiment_sha256"] or not checked["passed"]:
            raise ValueError("Corpus check does not match the completed experiment")
        write_json(output / "corpus-check.json", checked)
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    provenance = {
        "execution_code_commit": commit,
        "source_sha256": manifest["source_sha256"],
        "corpus_matches_frozen_inputs": load_experiment(
            ROOT / "benchmarks/stage3/experiment.json"
        ).sha256
        == manifest["experiment_sha256"],
        "raw_records": len(rows),
        "raw_jsonl_sha256": hashlib.sha256(raw).hexdigest(),
        "redactions": "HTTP headers never recorded; host paths replaced in failed grader logs.",
        "text_encoding": "UTF-8 with LF; candidate_sha256 hashes the normalized candidate text",
        "raw_fields": [
            "run metadata",
            "all recorded model requests/responses",
            "candidate code",
            "failed grader log with host paths redacted",
        ],
        "not_in_archive": ["API keys", "environment files", "account balance"],
    }
    write_json(output / "provenance.json", provenance)
    # Match Git's LF normalization so hashes remain valid after clone on other platforms.
    for path in output.iterdir():
        if path.suffix in (".json", ".jsonl", ".md"):
            path.write_bytes(path.read_text(encoding="utf-8").encode("utf-8"))
    checksums = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(output.iterdir())
        if path.is_file()
    }
    write_json(output / "checksums.json", checksums)
    path = output / "checksums.json"
    path.write_bytes(path.read_text(encoding="utf-8").encode("utf-8"))
    print(f"Exported {len(rows)} audited run records to {output}")


if __name__ == "__main__":
    main()
