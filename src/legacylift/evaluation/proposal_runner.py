"""Evaluate one explicitly reviewed candidate inside the evaluation container."""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from typing import Any

from legacylift.evaluation.plan import split_scenarios
from legacylift.runtime_capture.scenarios import DEFAULT_SCENARIOS
from legacylift.verification.runner import compare_scenarios

AGREEMENT_FIELDS = {
    "response_contract_agreement": (
        "response.status",
        "response.headers",
        "response.cookies",
        "response.json",
    ),
    "session_transition_agreement": ("session_before", "session_after"),
    "database_state_agreement": (
        "database_before",
        "database_after",
        "database_delta",
    ),
}


def _agreement_metric(steps: list[dict[str, Any]], fields: tuple[str, ...]) -> dict[str, Any]:
    compared = len(steps) * len(fields)
    matched = sum(
        not any(mismatch["field"] == field for mismatch in step["mismatches"])
        for step in steps
        for field in fields
    )
    return {
        "matched_field_count": matched,
        "compared_field_count": compared,
        "agreement_rate": matched / compared if compared else None,
    }


def evaluate_candidate(candidate_path: str | Path, condition: str) -> dict[str, Any]:
    """Load a reviewed module and compare it only against the held-out scenarios."""
    candidate = Path(candidate_path).resolve(strict=True)
    guidance, held_out = split_scenarios(DEFAULT_SCENARIOS)
    if not guidance or not held_out:
        raise ValueError("evaluation requires both guidance and held-out scenarios")

    spec = importlib.util.spec_from_file_location("legacylift_reviewed_candidate", candidate)
    if spec is None or spec.loader is None:
        raise ValueError("candidate must be a Python module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module

    # Keep candidate diagnostics out of the machine-readable result emitted by this process.
    with (
        contextlib.redirect_stdout(io.StringIO()),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        spec.loader.exec_module(module)
        app_factory = getattr(module, "create_app", None)
        if not callable(app_factory):
            raise ValueError("candidate must define callable create_app(test_config)")
        differential = compare_scenarios(
            held_out,
            reconstructed_app_factory=app_factory,
            reconstructed_application="reviewed_model_generated_app",
        )

    summary = differential["summary"]
    steps = [step for scenario in differential["scenarios"] for step in scenario["steps"]]
    scenarios = differential["scenarios"]
    scenario_count = len(scenarios)
    step_count = len(steps)
    passed_scenarios = sum(scenario["passed"] for scenario in scenarios)
    passed_steps = summary["passed_step_count"]
    return {
        "status": "evaluated",
        "condition": condition,
        "scope": "held-out scenarios only",
        "passed": summary["passed"],
        "scenario_count": scenario_count,
        "scenario_match_count": passed_scenarios,
        "scenario_match_rate": passed_scenarios / scenario_count if scenario_count else None,
        "step_count": step_count,
        "passed_step_count": passed_steps,
        "step_match_rate": passed_steps / step_count if step_count else None,
        "failed_step_count": summary["failed_step_count"],
        "metrics": {
            metric: _agreement_metric(steps, fields) for metric, fields in AGREEMENT_FIELDS.items()
        },
        "differential_report": differential,
        "unsupported_behavior_count": {
            "status": "not_measured",
            "reason": "Differential mismatches are not classified by cause or supportability.",
        },
        "human_correction_effort": {
            "status": "not_measured",
            "reason": "No human correction session was timed or logged.",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="legacylift-proposal-runner")
    parser.add_argument("--candidate-code", type=Path, required=True)
    parser.add_argument(
        "--condition", choices=("source_only", "runtime_only", "hybrid"), required=True
    )
    arguments = parser.parse_args(argv)
    try:
        report = evaluate_candidate(arguments.candidate_code, arguments.condition)
    except Exception as error:
        print(
            json.dumps(
                {
                    "status": "execution_failed",
                    "condition": arguments.condition,
                    "error_type": type(error).__name__,
                    "error": str(error)[:500],
                },
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
