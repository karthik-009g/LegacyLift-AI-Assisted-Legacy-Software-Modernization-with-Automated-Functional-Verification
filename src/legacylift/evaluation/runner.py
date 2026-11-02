"""Build guidance-only evidence and measure the manual baseline on held-out cases."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
from pathlib import Path
from typing import Any

from legacylift.evidence.builder import build_eer
from legacylift.evidence.schema import EngineeringEvidenceRecord
from legacylift.evidence.storage import write_eer
from legacylift.reconstruction import build_reconstruction_request
from legacylift.reconstruction.models import EvidenceCondition
from legacylift.reconstruction.prompts import build_reconstruction_prompt
from legacylift.runtime_capture.runner import capture_scenarios
from legacylift.runtime_capture.scenarios import DEFAULT_SCENARIOS
from legacylift.static_analysis import analyze_paths
from legacylift.verification.runner import compare_scenarios

from .plan import HELD_OUT_SCENARIO_IDS, split_scenarios

CONDITIONS: tuple[EvidenceCondition, ...] = ("source_only", "runtime_only", "hybrid")
EVALUATION_SCHEMA_VERSION = "1.0"
RUNTIME_PACKAGES = ("fastapi", "flask", "httpx", "pydantic", "starlette")


def _stable_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))).encode(
        "utf-8"
    )


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _source_digest(source_root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(source_root.rglob("*.py")):
        relative_path = path.relative_to(source_root).as_posix()
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


def _condition_audit(record: EngineeringEvidenceRecord, project_root: Path) -> list[dict[str, Any]]:
    held_out_ids = set(HELD_OUT_SCENARIO_IDS)
    results = []
    for condition in CONDITIONS:
        request = build_reconstruction_request(
            record,
            condition,
            source_root=project_root,
            max_source_chars=2_000,
            max_contracts=24,
            max_context_chars=18_000,
        )
        runtime_workflows = sorted({item["workflow_id"] for item in request.contracts})
        leaked_workflows = sorted(held_out_ids.intersection(runtime_workflows))
        if leaked_workflows:
            raise ValueError(
                f"held-out runtime evidence leaked into {condition}: {leaked_workflows}"
            )

        prompt = build_reconstruction_prompt(request)
        results.append(
            {
                "condition": condition,
                "status": "context_prepared_reconstruction_not_run",
                "selected_evidence_counts": {
                    "facts": len(request.facts),
                    "inferences": len(request.inferences),
                    "unknowns": len(request.unknowns),
                    "runtime_contracts": len(request.contracts),
                },
                "runtime_workflows": runtime_workflows,
                "held_out_runtime_workflows_in_context": leaked_workflows,
                "source_excerpt_char_count": len(request.source_excerpt),
                "source_excerpt_truncated": request.source_excerpt_truncated,
                "omitted_evidence_count": len(request.omitted_evidence_ids),
                "prompt_char_count": len(prompt),
                "prompt_sha256": _sha256(prompt.encode("utf-8")),
                "external_provider_calls": 0,
                "executable_reconstruction_generated": False,
            }
        )
    return results


def _runtime_versions() -> dict[str, str]:
    return {package: importlib.metadata.version(package) for package in RUNTIME_PACKAGES}


def run_evaluation(
    project_root: str | Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], EngineeringEvidenceRecord]:
    """Build a reproducible evaluation report without calling an external model."""
    root = Path(project_root or Path(__file__).resolve().parents[3]).resolve()
    guidance_scenarios, held_out_scenarios = split_scenarios(DEFAULT_SCENARIOS)
    full_trace = capture_scenarios()
    traces_by_id = {item["scenario_id"]: item for item in full_trace["scenarios"]}
    guidance_ids = {scenario.scenario_id for scenario in guidance_scenarios}
    guidance_trace = {
        **{key: value for key, value in full_trace.items() if key != "scenarios"},
        "scenarios": [
            traces_by_id[scenario_id]
            for scenario_id in (scenario.scenario_id for scenario in guidance_scenarios)
        ],
    }

    analysis = analyze_paths([root / "src" / "legacylift" / "legacy_app"], root=root)
    record = build_eer(
        analysis,
        guidance_trace,
        trace_artifact="artifacts/evaluation/guidance_trace.json",
        record_id="legacylift-ticket-workflows-guidance-v1",
    )
    evidence_workflows = {contract.workflow_id for contract in record.contracts}
    if not evidence_workflows <= guidance_ids:
        raise ValueError("guidance EER contains runtime contracts outside the guidance split")

    held_out_report = compare_scenarios(held_out_scenarios)
    held_out_summary = held_out_report["summary"]
    scenario_count = held_out_summary["scenario_count"]
    step_count = held_out_summary["step_count"]
    scenario_match_count = sum(scenario["passed"] for scenario in held_out_report["scenarios"])
    passed_step_count = held_out_summary["passed_step_count"]
    context_audit = _condition_audit(record, root)

    report = {
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
        "study": "initial_ticket_workflow_evidence_conditions",
        "scenario_partition": {
            "guidance": [scenario.scenario_id for scenario in guidance_scenarios],
            "held_out": [scenario.scenario_id for scenario in held_out_scenarios],
        },
        "input_fingerprints": {
            "legacy_source_sha256": _source_digest(root / "src" / "legacylift" / "legacy_app"),
            "complete_runtime_trace_sha256": _sha256(_stable_json(full_trace)),
            "guidance_runtime_trace_sha256": _sha256(_stable_json(guidance_trace)),
        },
        "environment": {
            "python": platform.python_version(),
            "packages": _runtime_versions(),
        },
        "baseline_result": {
            "implementation": "hand_built_fastapi_baseline",
            "scope": "held-out scenarios only",
            "passed": held_out_summary["passed"],
            "scenario_count": scenario_count,
            "scenario_match_count": scenario_match_count,
            "scenario_match_rate": scenario_match_count / scenario_count,
            "step_count": step_count,
            "passed_step_count": passed_step_count,
            "step_match_rate": passed_step_count / step_count,
            "failed_step_count": held_out_summary["failed_step_count"],
            "differential_report": held_out_report,
        },
        "condition_audit": context_audit,
        "strategy_comparison": {
            "status": "not_run",
            "reason": (
                "The repository has a hand-built FastAPI baseline and an offline mock provider, "
                "but no model-generated reconstruction for any evidence condition."
            ),
            "conditions": {condition: "context_prepared_only" for condition in CONDITIONS},
            "comparative_claims_supported": False,
        },
        "methodology": {
            "guidance_evidence": (
                "Only runtime traces from the guidance split enter the guidance EER."
            ),
            "source_condition": (
                "Source-only uses static findings and source excerpts from the complete legacy "
                "application; source code includes held-out branch implementations."
            ),
            "runtime_condition": "Runtime-only receives guidance traces and no source excerpt.",
            "hybrid_condition": "Hybrid receives source findings/excerpts and guidance traces.",
            "metrics": {
                "scenario_match_rate": (
                    "Held-out scenarios with every compared step matching / held-out scenarios."
                ),
                "step_match_rate": (
                    "Held-out steps with all compared fields matching / held-out steps."
                ),
            },
        },
        "limitations": [
            "The evaluation uses six small, synthetic scenarios and one ticket workflow.",
            "The FastAPI baseline was written by hand, not generated under an evidence condition.",
            "The guidance/held-out split is fixed and not repeated with alternative partitions.",
            "Source-only and hybrid contexts include source code for held-out branches.",
            "Correction time, generated-code quality, and model cost are not measured.",
        ],
    }
    return guidance_trace, report, record


def _write_json(value: Any, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


def write_evaluation_artifacts(
    output_directory: str | Path,
    project_root: str | Path | None = None,
) -> dict[str, Path]:
    """Write guidance-only runtime/EER inputs and the reproducible report."""
    guidance_trace, report, record = run_evaluation(project_root)
    output = Path(output_directory)
    guidance_trace_path = _write_json(guidance_trace, output / "guidance_trace.json")
    eer_path = write_eer(record, output / "guidance_eer.json")
    report_path = _write_json(report, output / "evaluation_report.json")
    return {
        "guidance_trace": guidance_trace_path,
        "guidance_eer": eer_path,
        "evaluation_report": report_path,
    }
