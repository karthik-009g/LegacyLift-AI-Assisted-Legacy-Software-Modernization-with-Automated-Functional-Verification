"""Command-line entry point for the deterministic end-to-end demo."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from legacylift.evaluation import write_evaluation_artifacts
from legacylift.evidence.builder import build_eer
from legacylift.evidence.storage import load_eer, write_eer, write_eer_schema
from legacylift.reconstruction import GroqProvider, build_reconstruction_request
from legacylift.reconstruction.context import (
    DEFAULT_MAX_CONTEXT_CHARS,
    DEFAULT_MAX_CONTRACTS,
    DEFAULT_MAX_SOURCE_CHARS,
)
from legacylift.reconstruction.models import EvidenceCondition
from legacylift.runtime_capture.runner import write_trace_bundle
from legacylift.static_analysis import analyze_paths, write_analysis_report
from legacylift.verification.runner import (
    write_differential_report,
    write_sample_mismatch_report,
)


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
    sample_mismatch_path = write_sample_mismatch_report(
        artifact_root / "verification" / "sample_mismatch.json"
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
                sample_mismatch_path,
                *evaluation_paths.values(),
            )
        ],
    }


def run_proposal(
    condition: EvidenceCondition,
    *,
    model: str = GroqProvider.DEFAULT_MODEL,
    timeout: float = 90.0,
    project_root: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Call Groq once and save its proposal without executing generated code."""
    root = Path(project_root or Path(__file__).resolve().parents[2]).resolve()
    guidance_eer = load_eer(root / "artifacts" / "evaluation" / "guidance_eer.json")
    request = build_reconstruction_request(
        guidance_eer,
        condition,
        source_root=root,
        max_source_chars=DEFAULT_MAX_SOURCE_CHARS,
        max_contracts=DEFAULT_MAX_CONTRACTS,
        max_context_chars=DEFAULT_MAX_CONTEXT_CHARS,
    )
    proposal = GroqProvider.from_environment(model=model, timeout=timeout).propose(request)
    destination = (
        Path(output_path) if output_path else Path("artifacts" / "proposals" / f"{condition}.json")
    )
    if not destination.is_absolute():
        destination = root / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(proposal.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "status": "proposal_saved",
        "provider": proposal.provider,
        "model": proposal.model,
        "condition": proposal.condition,
        "summary": proposal.summary,
        "proposal_contains_code": proposal.proposed_code is not None,
        "requires_human_review": proposal.requires_human_review,
        "prompt_sha256": proposal.prompt_sha256,
        "usage": proposal.usage,
        "proposal_path": destination.relative_to(root).as_posix()
        if destination.is_relative_to(root)
        else str(destination),
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
    propose_parser = subparsers.add_parser(
        "propose",
        help="ask Groq for a cloud model proposal that is saved for human review",
    )
    propose_parser.add_argument(
        "--condition", choices=("source_only", "runtime_only", "hybrid"), required=True
    )
    propose_parser.add_argument("--model", default=GroqProvider.DEFAULT_MODEL)
    propose_parser.add_argument("--timeout", type=float, default=90.0)
    propose_parser.add_argument("--root", type=Path, default=None)
    propose_parser.add_argument("--output", type=Path, default=None)
    arguments = parser.parse_args(argv)
    if arguments.command == "demo":
        result = run_demo(arguments.root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "passed" else 1
    if arguments.command == "propose":
        result = run_proposal(
            arguments.condition,
            model=arguments.model,
            timeout=arguments.timeout,
            project_root=arguments.root,
            output_path=arguments.output,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    if arguments.command is None:
        parser.print_help()
        return 2
    parser.error(f"unknown command: {arguments.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
