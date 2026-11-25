"""Read recorded Docker experiments without executing candidates or calling a model."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from legacylift.reconstruction.models import ReconstructionProposal


def recorded_comparison(root: Path, prompt_hashes: dict[str, str]) -> dict[str, Any] | None:
    """Include results only when saved candidate and current prompt hashes agree."""
    directory = root / "artifacts" / "experiments"
    report_paths = {
        "raw_model_output": directory / "raw_comparison.json",
        "compatibility_repaired": directory / "compatibility_comparison.json",
    }
    if not any(path.exists() for path in report_paths.values()):
        return None

    summaries = {}
    raw_hashes = {}
    for label, report_path in report_paths.items():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("status") not in {"completed", "completed_with_candidate_failures"}:
            raise ValueError(f"recorded experiment did not complete: {label}")
        proposal_directory = directory / (
            "raw_proposals" if label == "raw_model_output" else "compatibility_repaired"
        )
        conditions = {}
        for condition, expected_prompt in prompt_hashes.items():
            proposal = ReconstructionProposal.model_validate_json(
                (proposal_directory / f"{condition}.json").read_text(encoding="utf-8")
            )
            result = report["conditions"][condition]
            if (
                result.get("status") == "evaluation_failed"
                and result.get("failure_category") != "candidate"
            ):
                raise ValueError(f"recorded experiment has an infrastructure failure: {condition}")
            candidate_hash = hashlib.sha256((proposal.proposed_code or "").encode()).hexdigest()
            if (
                proposal.condition != condition
                or proposal.prompt_sha256 != expected_prompt
                or result.get("prompt_sha256") != expected_prompt
                or result.get("candidate_sha256") != candidate_hash
                or result.get("status") not in {"evaluated", "evaluation_failed"}
            ):
                raise ValueError(
                    f"recorded experiment is stale or inconsistent: {label}/{condition}"
                )
            if label == "raw_model_output":
                if proposal.derivation:
                    raise ValueError("raw model experiment contains a derived candidate")
                raw_hashes[condition] = candidate_hash
            elif (
                not proposal.derivation
                or proposal.derivation.parent_candidate_sha256 != raw_hashes[condition]
                or result.get("derivation") != proposal.derivation.model_dump(mode="json")
            ):
                raise ValueError(f"recorded repair provenance is inconsistent: {condition}")
            conditions[condition] = {
                key: result[key]
                for key in (
                    "status",
                    "error",
                    "candidate_sha256",
                    "scenario_match_rate",
                    "step_match_rate",
                    "metrics",
                )
                if key in result
            }
        canonical = json.dumps(report, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        summaries[label] = {
            "run_status": report["status"],
            "functional_evaluation_complete": report.get("functional_evaluation_complete", False),
            "experiment_metrics": report.get("experiment_metrics", {}),
            "runtime": report["runtime"],
            "reviewer": report["reviewer"],
            "report_path": report_path.relative_to(root).as_posix(),
            "report_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "conditions": conditions,
        }
    return {
        "status": "recorded",
        "reason": "Raw outcomes and a separate agent repair experiment are recorded.",
        **summaries,
        "comparative_claims_supported": False,
        "limitations": [
            "Two raw drafts fail import; only runtime-only has raw functional agreement rates.",
            "The repaired study includes agent changes and is not a raw model comparison.",
            "One draft per condition and one synthetic split cannot establish superiority.",
            "Human correction effort and independent unsupported behavior counts are unmeasured.",
        ],
    }
