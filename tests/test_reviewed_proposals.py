from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from legacylift.evaluation.proposal_runner import evaluate_candidate
from legacylift.evaluation.reviewed import (
    EVALUATION_IMAGE,
    run_candidate_in_container,
    run_reviewed_proposals,
)


def test_candidate_evaluator_uses_only_held_out_scenarios(tmp_path):
    candidate = Path(__file__).parent / "fixtures" / "baseline_candidate.py"

    report = evaluate_candidate(candidate, "hybrid")

    assert report["status"] == "evaluated"
    assert report["scope"] == "held-out scenarios only"
    assert report["passed"] is True
    assert report["scenario_count"] == 3
    assert report["step_count"] == 6
    assert report["metrics"]["response_contract_agreement"]["agreement_rate"] == 1.0
    assert report["metrics"]["session_transition_agreement"]["agreement_rate"] == 1.0
    assert report["metrics"]["database_state_agreement"]["agreement_rate"] == 1.0
    assert {scenario["scenario_id"] for scenario in report["differential_report"]["scenarios"]} == {
        "hide_other_users_ticket",
        "reject_empty_subject",
        "reject_skipped_status",
    }


def test_candidate_evaluator_rejects_module_without_app_factory(tmp_path):
    candidate = tmp_path / "candidate.py"
    candidate.write_text("value = 1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="define callable create_app"):
        evaluate_candidate(candidate, "source_only")


def test_reviewed_proposals_requires_explicit_review(tmp_path):
    with pytest.raises(ValueError, match="--human-reviewed"):
        run_reviewed_proposals(tmp_path, human_reviewed=False)


def test_reviewed_proposals_reports_missing_inputs_without_running_docker(tmp_path):
    output = tmp_path / "comparison.json"

    report = run_reviewed_proposals(
        tmp_path,
        human_reviewed=True,
        output_path=output,
    )

    assert report["status"] == "incomplete"
    assert all(result["status"] == "missing_proposal" for result in report["conditions"].values())
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert report["comparative_claims_supported"] is False


@pytest.mark.skipif(
    os.environ.get("LEGACYLIFT_DOCKER_SMOKE") != "1",
    reason="Docker integration is enabled only in CI",
)
def test_reviewed_candidate_runs_in_restricted_docker_container():
    if shutil.which("docker") is None:
        pytest.fail("CI requested Docker smoke test but the Docker CLI is unavailable")
    info = subprocess.run(["docker", "info"], capture_output=True, check=False, timeout=30)
    if info.returncode:
        pytest.fail("CI requested Docker smoke test but the Docker daemon is unavailable")
    image = subprocess.run(
        ["docker", "image", "inspect", EVALUATION_IMAGE],
        capture_output=True,
        check=False,
        timeout=30,
    )
    if image.returncode:
        pytest.fail("CI must build Dockerfile.evaluation before running tests")

    source = (Path(__file__).parent / "fixtures" / "baseline_candidate.py").read_text(
        encoding="utf-8"
    )
    report = run_candidate_in_container(source, "hybrid")

    assert report["passed"] is True
    assert report["scenario_count"] == 3
    assert report["step_count"] == 6
