"""Command-line entry point for the deterministic end-to-end demo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from legacylift.evaluation import write_evaluation_artifacts
from legacylift.evidence.builder import build_eer
from legacylift.evidence.storage import write_eer, write_eer_schema
from legacylift.runtime_capture.runner import write_trace_bundle
from legacylift.static_analysis import analyze_paths, write_analysis_report
from legacylift.verification.runner import write_differential_report


def run_demo(project_root: str | Path | None = None) -> dict[str, Any]:
    """Rebuild all artifacts in dependency order and return a concise result."""
    root = Path(project_root or Path(__file__).resolve().parents[2]).resolve()
    artifact_root = root / "artifacts"

    trace_path = write_trace_bundle(artifact_root / "traces" / "ticket_workflows.json")
    trace_bundle = json.loads(trace_path.read_text(encoding="utf-8"))

    static_report = analyze_paths(
        [root / "src" / "legacylift" / "legacy_app"],
        root=root,
    )
    static_path = write_analysis_report(
        static_report,
        artifact_root / "static" / "legacy_analysis.json",
    )
    eer = build_eer(static_report, trace_bundle)
    eer_path = write_eer(eer, artifact_root / "evidence" / "ticket_workflows.eer.json")
    schema_path = write_eer_schema(
        artifact_root / "schemas" / "engineering_evidence_record.schema.json"
    )

    differential_path = write_differential_report(
        artifact_root / "verification" / "differential_report.json"
    )
    evaluation_paths = write_evaluation_artifacts(artifact_root / "evaluation", root)
    differential = json.loads(differential_path.read_text(encoding="utf-8"))
    evaluation = json.loads(evaluation_paths["evaluation_report"].read_text(encoding="utf-8"))

    passed = differential["summary"]["passed"] and evaluation["baseline_result"]["passed"]
    return {
        "status": "passed" if passed else "failed",
        "differential_verification": differential["summary"],
        "held_out_baseline": {
            "scenario_count": evaluation["baseline_result"]["scenario_count"],
            "scenario_match_rate": evaluation["baseline_result"]["scenario_match_rate"],
            "step_count": evaluation["baseline_result"]["step_count"],
            "step_match_rate": evaluation["baseline_result"]["step_match_rate"],
        },
        "model_condition_comparison": evaluation["strategy_comparison"]["status"],
        "artifacts_written": [
            str(path.relative_to(root).as_posix())
            for path in (
                trace_path,
                static_path,
                eer_path,
                schema_path,
                differential_path,
                *evaluation_paths.values(),
            )
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="legacylift")
    subparsers = parser.add_subparsers(dest="command")
    demo_parser = subparsers.add_parser("demo", help="rebuild artifacts and run local verification")
    demo_parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="project root (defaults to the installed LegacyLift checkout)",
    )
    arguments = parser.parse_args(argv)
    if arguments.command != "demo":
        parser.print_help()
        return 2

    result = run_demo(arguments.root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
