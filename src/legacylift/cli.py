"""Command-line entry point for the deterministic end-to-end demo."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from legacylift.evaluation import run_reviewed_proposals, write_evaluation_artifacts
from legacylift.evidence.builder import build_eer
from legacylift.evidence.storage import load_eer, write_eer, write_eer_schema
from legacylift.reconstruction import (
    GeminiProvider,
    ProviderFallback,
    build_reconstruction_request,
)
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


def _load_project_env(path: Path) -> None:
    """Load only the supported API keys from a local ignored .env file."""
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key not in {"GEMINI_API_KEY", "GROQ_API_KEY"} or os.environ.get(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value:
            os.environ[key] = value


def run_proposal(
    condition: EvidenceCondition,
    *,
    gemini_model: str = ProviderFallback.DEFAULT_GEMINI_MODEL,
    groq_model: str = ProviderFallback.DEFAULT_GROQ_MODEL,
    timeout: float = 90.0,
    project_root: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Call Gemini first, fall back to Groq, and save the review-only proposal."""
    root = Path(project_root or Path(__file__).resolve().parents[2]).resolve()
    _load_project_env(root / ".env")
    guidance_eer = load_eer(root / "artifacts" / "evaluation" / "guidance_eer.json")
    request = build_reconstruction_request(
        guidance_eer,
        condition,
        source_root=root,
        max_source_chars=DEFAULT_MAX_SOURCE_CHARS,
        max_contracts=DEFAULT_MAX_CONTRACTS,
        max_context_chars=DEFAULT_MAX_CONTEXT_CHARS,
    )
    proposal = ProviderFallback.from_environment(
        gemini_model=gemini_model,
        groq_model=groq_model,
        timeout=timeout,
    ).propose(request)
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
        help="ask Gemini first, use Groq as backup, and save the proposal for human review",
    )
    propose_parser.add_argument(
        "--condition", choices=("source_only", "runtime_only", "hybrid"), required=True
    )
    propose_parser.add_argument("--gemini-model", default=GeminiProvider.DEFAULT_MODEL)
    propose_parser.add_argument(
        "--groq-model",
        "--model",
        dest="groq_model",
        default=ProviderFallback.DEFAULT_GROQ_MODEL,
    )
    propose_parser.add_argument("--timeout", type=float, default=90.0)
    propose_parser.add_argument("--root", type=Path, default=None)
    propose_parser.add_argument("--output", type=Path, default=None)
    evaluate_parser = subparsers.add_parser(
        "evaluate-proposals",
        help="evaluate reviewed model proposals in an isolated Docker container",
    )
    evaluate_parser.add_argument(
        "--human-reviewed",
        action="store_true",
        required=True,
        help="declare that every proposal's code was inspected before execution",
    )
    evaluate_parser.add_argument("--root", type=Path, default=None)
    evaluate_parser.add_argument("--proposal-directory", type=Path, default=None)
    evaluate_parser.add_argument("--output", type=Path, default=None)
    evaluate_parser.add_argument("--timeout", type=float, default=180.0)
    arguments = parser.parse_args(argv)
    if arguments.command == "demo":
        result = run_demo(arguments.root)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "passed" else 1
    if arguments.command == "propose":
        try:
            result = run_proposal(
                arguments.condition,
                gemini_model=arguments.gemini_model,
                groq_model=arguments.groq_model,
                timeout=arguments.timeout,
                project_root=arguments.root,
                output_path=arguments.output,
            )
        except (RuntimeError, ValueError) as error:
            parser.error(str(error))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if arguments.command == "evaluate-proposals":
        root = Path(arguments.root or Path(__file__).resolve().parents[2]).resolve()
        try:
            result = run_reviewed_proposals(
                root,
                human_reviewed=arguments.human_reviewed,
                proposals_directory=(arguments.proposal_directory or Path("artifacts/proposals")),
                output_path=(
                    arguments.output or Path("artifacts/proposals/model_generated_comparison.json")
                ),
                timeout=arguments.timeout,
            )
        except (RuntimeError, ValueError) as error:
            parser.error(str(error))
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "completed" else 1

    if arguments.command is None:
        parser.print_help()
        return 2
    parser.error(f"unknown command: {arguments.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
