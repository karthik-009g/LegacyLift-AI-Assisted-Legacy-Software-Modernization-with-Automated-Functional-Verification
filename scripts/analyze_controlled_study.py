"""Export descriptive study analysis from audited artifacts, without provider calls."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from summarize_controlled_study import save_checkpoint

from legacylift.modernization.contracts import canonical_hash
from legacylift.modernization.study_execution import study_report


def wilson_interval(successes: int, total: int) -> list[float] | None:
    """Nominal 95% binomial interval, descriptive under independent-trial assumptions."""
    if type(successes) is not int or type(total) is not int or not 0 <= successes <= total:
        raise ValueError("success counts must be integers within the denominator")
    if total == 0:
        return None
    z = 1.959963984540054
    fraction = successes / total
    denominator = 1 + z * z / total
    center = (fraction + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(fraction * (1 - fraction) / total + z * z / (4 * total**2))
    radius /= denominator
    return [round(max(0, center - radius), 6), round(min(1, center + radius), 6)]


def describe(values: list[float]) -> dict:
    if not values:
        return {"observations": 0, "median": None, "minimum": None, "maximum": None}
    return {
        "observations": len(values),
        "median": round(statistics.median(values), 3),
        "minimum": round(min(values), 3),
        "maximum": round(max(values), 3),
    }


def analyze(report: dict, results: dict[str, dict]) -> dict:
    """Project only guidance counts and provenance, excluding source and hidden mismatches."""
    rows = []
    for record in report["records"]:
        run_id = record["cell"]["run_id"]
        result = results[run_id]
        attempts = result.get("attempts", [])
        replays = [a for a in attempts if a.get("scenario_count") == 6]
        initial = next((a for a in replays if a.get("attempt") == 0), None)
        final = replays[-1] if replays else None
        latencies = []
        for attempt in attempts:
            value = attempt.get("provenance", {}).get("latency_seconds")
            if value is None:
                continue
            if type(value) not in {int, float} or not math.isfinite(value) or value < 0:
                raise ValueError("invalid recorded provider latency")
            latencies.append(value)
        rows.append(
            {
                **record["cell"],
                "status": record["status"],
                "failure_category": record["failure_category"],
                "workflow_passed": record["workflow_passed"],
                "guidance_passed": record["guidance_passed"],
                "held_out_evaluated": record["held_out_evaluated"],
                "requests": record["requests_consumed"],
                "unknown_usage_requests": record["requests_without_token_usage"],
                "reported_tokens": record["reported_tokens"],
                "parsed_outputs": len(attempts),
                "guidance_replays": len(replays),
                "initial_guidance_passed_count": initial["passed_count"] if initial else None,
                "last_replayed_guidance_passed_count": final["passed_count"] if final else None,
                "paired_initial_final_replay": initial is not None and len(replays) > 1,
                "recorded_provider_latencies_seconds": latencies,
            }
        )
    groups = []
    for condition in ("source_only", "runtime_only", "hybrid"):
        selected = [row for row in rows if row["condition"] == condition]
        paired = [row for row in selected if row["paired_initial_final_replay"]]
        successes = sum(row["workflow_passed"] for row in selected)
        groups.append(
            {
                "condition": condition,
                "planned_trials": report["condition_counts"][condition]["planned"],
                "recorded_trials": len(selected),
                "outcome_counts": dict(Counter(row["status"] for row in selected)),
                "guidance_passing_trials": sum(row["guidance_passed"] for row in selected),
                "held_out_evaluated_trials": sum(row["held_out_evaluated"] for row in selected),
                "workflow_passing_trials": successes,
                "workflow_pass_fraction_of_recorded": successes / len(selected)
                if selected
                else None,
                "nominal_wilson_95_percent": wilson_interval(successes, len(selected)),
                "requests": sum(row["requests"] for row in selected),
                "reported_tokens": sum(row["reported_tokens"] for row in selected),
                "unknown_usage_requests": sum(row["unknown_usage_requests"] for row in selected),
                "provider_latency_seconds": describe(
                    [v for row in selected for v in row["recorded_provider_latencies_seconds"]]
                ),
                "paired_repair_trials": len(paired),
                "paired_repair_improved_trials": sum(
                    row["last_replayed_guidance_passed_count"]
                    > row["initial_guidance_passed_count"]
                    for row in paired
                ),
                "paired_repair_regressed_trials": sum(
                    row["last_replayed_guidance_passed_count"]
                    < row["initial_guidance_passed_count"]
                    for row in paired
                ),
            }
        )
    return {
        "version": 1,
        "study_id": report["study_id"],
        "audited_report_sha256": canonical_hash(report),
        "state": report["state"],
        "recorded_trials": report["recorded_trials"],
        "planned_trials": report["planned_trials"],
        "groups": groups,
        "trials": rows,
        "limitations": [
            "Descriptive analysis of one repository and three selected workflows.",
            "Recorded-trial denominators include provider, static and boot failures. "
            "Pending trials, if any, are excluded. This measures observed end-to-end yield.",
            "Repeated trials share code, fixtures and provider conditions. Nominal Wilson "
            "intervals assume independent binomial trials and do not establish generalization "
            "or a significant difference between conditions.",
            "Reported tokens omit unknown usage. Latencies cover only recorded parsed outputs "
            "and exclude pacing, failed HTTP requests, container work and total wall-clock time.",
            "Repair pairs require an initial six-case replay and a later six-case replay. "
            "Attempts without replay are excluded from paired counts.",
            "The last replay may precede a terminal static/provider failure. Its partial score "
            "is not a terminal guidance pass or a held-out result.",
            "This single-repository study does not establish general superiority of an "
            "evidence condition.",
        ],
    }


def export_analysis(home: Path, study_id: str, output: Path) -> dict:
    report = study_report(home, study_id)
    results = {}
    for record in report["records"]:
        path = home / "runs" / record["cell"]["run_id"] / "result.json"
        text = path.read_text(encoding="utf-8")
        if path.is_symlink() or canonical_hash(text) != record["artifacts"]["result.json"]:
            raise ValueError("result changed after study audit")
        results[record["cell"]["run_id"]] = json.loads(text)
    analysis = analyze(report, results)
    suffix = f"{report['recorded_trials']:03d}"
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"analysis-{suffix}.json"
    save_checkpoint(path, json.dumps(analysis, indent=2) + "\n")
    lines = [
        f"# Study analysis at {report['recorded_trials']}/{report['planned_trials']} trials",
        "",
        "| Condition | Recorded / planned | Guidance passes | Held-out evaluated | "
        "Workflow passes | HTTP requests | Unknown token usage |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for group in analysis["groups"]:
        lines.append(
            f"| {group['condition']} | {group['recorded_trials']}/{group['planned_trials']} | "
            f"{group['guidance_passing_trials']} | {group['held_out_evaluated_trials']} | "
            f"{group['workflow_passing_trials']} | {group['requests']} | "
            f"{group['unknown_usage_requests']} |"
        )
    lines += ["", *[f"- {limit}" for limit in analysis["limitations"]], ""]
    lines += [f"[Full descriptive analysis]({path.name})", ""]
    save_checkpoint(output / f"analysis-{suffix}.md", "\n".join(lines))
    return {"study_id": study_id, "recorded_trials": report["recorded_trials"], "path": str(path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study_id")
    parser.add_argument("--home", type=Path, default=Path(".legacylift"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or Path("artifacts/v2/studies") / args.study_id
    print(json.dumps(export_analysis(args.home, args.study_id, output)))


if __name__ == "__main__":
    main()
