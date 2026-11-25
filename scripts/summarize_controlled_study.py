"""Export audited, immutable per-checkpoint tables without model calls or new trials."""

from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path

from legacylift.modernization.study_execution import study_report


def save_checkpoint(path: Path, text: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") != text:
            raise ValueError(f"refusing to overwrite a different recorded checkpoint: {path.name}")
        return
    path.write_text(text, encoding="utf-8")


def export_summary(home: Path, study_id: str, output: Path) -> dict:
    # The real reporter locks/audits source artifacts, protocol and ledger. Never
    # trust an arbitrary JSON summary supplied by a caller, or bypass a live runner.
    report = study_report(home, study_id)
    records = report["records"]
    count = report["recorded_trials"]
    suffix = f"{count:03d}"
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / f"report-{suffix}.json"
    csv_path = output / f"trials-{suffix}.csv"
    markdown_path = output / f"summary-{suffix}.md"
    fields = [
        "run_id",
        "workflow",
        "condition",
        "replicate",
        "status",
        "failure_category",
        "guidance_passed_count",
        "guidance_scenario_count",
        "held_out_evaluated",
        "held_out_passed_count",
        "held_out_scenario_count",
        "workflow_passed",
        "requests_consumed",
        "reported_tokens",
        "requests_without_token_usage",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for record in records:
        row = {**record, **record["cell"]}
        writer.writerow({key: row.get(key) for key in fields})
    lines = [
        f"# Controlled study {study_id}",
        "",
        f"Audited checkpoint: **{count}/{report['planned_trials']} trials recorded**; "
        f"study state **{report['state']}**.",
        "",
        f"Guidance passes: {report['guidance_passing_trials']}. "
        f"Held-out evaluations: {report['held_out_evaluated_trials']}. "
        f"Full-workflow passes: {report['workflow_passing_trials']}.",
        "",
        f"HTTP reservations: {report['requests_consumed']}/{report['maximum_http_requests']} "
        f"maximum. Reported tokens: {report['reported_tokens']:,}. "
        f"Requests without token usage: {report['requests_without_token_usage']}.",
        "",
        (
            "Unrecorded cells are pending, not passes or observed failures. "
            "An incomplete study establishes no condition superiority."
            if report["state"] != "completed"
            else "All planned cells are recorded; no pending outcome is imputed. "
            "Recorded results do not establish condition superiority."
        )
        + " Token totals omit unreported usage. Compatibility is separate from "
        "human approval and security assessment.",
        "",
        "## Workflow and condition coverage",
        "",
        "| Workflow | Condition | Recorded / planned | Guidance passes | "
        "Workflow passes | Requests |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for workflow in ("create", "read", "update"):
        for condition in ("source_only", "runtime_only", "hybrid"):
            selected = [
                r
                for r in records
                if r["cell"]["workflow"] == workflow and r["cell"]["condition"] == condition
            ]
            lines.append(
                f"| {workflow} | {condition} | {len(selected)} / 3 | "
                f"{sum(r['guidance_passed'] for r in selected)} | "
                f"{sum(r['workflow_passed'] for r in selected)} | "
                f"{sum(r['requests_consumed'] for r in selected)} |"
            )
    lines += [
        "",
        "## Recorded outcomes",
        "",
        "| Run | Workflow | Condition | Status | Final guidance | Held-out |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for record in records:
        cell = record["cell"]
        guidance = (
            f"{record['guidance_passed_count']}/{record['guidance_scenario_count']}"
            if record["guidance_scenario_count"]
            else "not replayed"
        )
        held_out = (
            f"{record['held_out_passed_count']}/{record['held_out_scenario_count']}"
            if record["held_out_evaluated"]
            else "not evaluated"
        )
        lines.append(
            f"| {cell['run_id']} | {cell['workflow']} | {cell['condition']} | "
            f"{record['status']} | {guidance} | {held_out} |"
        )
    lines += [
        "",
        f"[Audited source report]({report_path.name}); [trial CSV]({csv_path.name}).",
        "",
        "A boot/static rejection with no replay is not labelled 0/6. "
        "Held-out failures remain final; no hidden mismatch payload is exported here.",
        "",
    ]
    save_checkpoint(report_path, json.dumps(report, indent=2) + "\n")
    save_checkpoint(csv_path, buffer.getvalue())
    save_checkpoint(markdown_path, "\n".join(lines))
    return {"study_id": study_id, "recorded_trials": count, "summary": str(markdown_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study_id")
    parser.add_argument("--home", type=Path, default=Path(".legacylift"))
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    output = arguments.output or Path("artifacts/v2/studies") / arguments.study_id
    print(json.dumps(export_summary(arguments.home, arguments.study_id, output)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
