from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from legacylift.evaluation.proposal_runner import evaluate_candidate
from legacylift.evaluation.reviewed import (
    EVALUATION_IMAGE,
    CandidateExecutionError,
    run_candidate_in_container,
    run_reviewed_proposals,
)
from legacylift.evidence.storage import load_eer
from legacylift.reconstruction.context import build_reconstruction_request
from legacylift.reconstruction.prompts import build_reconstruction_prompt


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


def test_container_execution_error_is_not_hidden_by_stderr_warnings(monkeypatch):
    monkeypatch.setattr(
        "legacylift.evaluation.reviewed.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1,
            stderr="StarletteDeprecationWarning: unrelated warning",
            stdout=json.dumps(
                {
                    "status": "execution_failed",
                    "error_type": "ModuleNotFoundError",
                    "error": "No module named 'fastapi.middleware.sessions'",
                }
            ),
        ),
    )

    with pytest.raises(RuntimeError, match="ModuleNotFoundError.*fastapi.middleware.sessions"):
        run_candidate_in_container("value = 1", "hybrid")


@pytest.mark.parametrize("stdout", ["not JSON", "[]", "null"])
def test_container_rejects_missing_or_non_object_reports(monkeypatch, stdout):
    monkeypatch.setattr(
        "legacylift.evaluation.reviewed.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=stdout, stderr=""),
    )

    with pytest.raises(RuntimeError, match="JSON report object"):
        run_candidate_in_container("value = 1", "hybrid")


def test_reviewed_proposals_requires_explicit_review(tmp_path):
    with pytest.raises(ValueError, match="--human-reviewed"):
        run_reviewed_proposals(tmp_path, human_reviewed=False)


def test_reviewed_proposals_rejects_conflicting_reviewer_declarations(tmp_path):
    with pytest.raises(ValueError, match="exactly one"):
        run_reviewed_proposals(tmp_path, human_reviewed=True, agent_reviewed=True)


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


def _write_proposal(directory, condition, prompt_sha256):
    directory.mkdir(parents=True, exist_ok=True)
    proposal = {
        "provider": "test-provider",
        "condition": condition,
        "summary": "Test proposal",
        "evidence_ids": [],
        "proposed_code": "def create_app(test_config=None):\n    return None\n",
        "requires_human_review": True,
        "prompt_sha256": prompt_sha256,
    }
    (directory / f"{condition}.json").write_text(json.dumps(proposal), encoding="utf-8")


def test_reviewed_proposals_rejects_a_stale_prompt_before_container_launch(tmp_path, monkeypatch):
    project_root = Path(__file__).parents[1]
    proposal_directory = tmp_path / "proposals"
    _write_proposal(proposal_directory, "source_only", "0" * 64)
    monkeypatch.setattr(
        "legacylift.evaluation.reviewed.run_candidate_in_container",
        lambda *args, **kwargs: pytest.fail("stale proposal must not be executed"),
    )

    report = run_reviewed_proposals(
        project_root,
        human_reviewed=True,
        proposals_directory=proposal_directory,
        output_path=tmp_path / "comparison.json",
    )

    result = report["conditions"]["source_only"]
    assert result["status"] == "stale_prompt"
    assert result["prompt_sha256"] == "0" * 64
    assert result["expected_prompt_sha256"] != result["prompt_sha256"]


def test_reviewed_proposals_accepts_current_prompt_hash(tmp_path, monkeypatch):
    project_root = Path(__file__).parents[1]
    proposal_directory = tmp_path / "proposals"
    record = load_eer(project_root / "artifacts" / "evaluation" / "guidance_eer.json")
    request = build_reconstruction_request(record, "source_only", source_root=project_root)
    prompt_digest = hashlib.sha256(build_reconstruction_prompt(request).encode("utf-8")).hexdigest()
    _write_proposal(proposal_directory, "source_only", prompt_digest)
    monkeypatch.setattr(
        "legacylift.evaluation.reviewed.run_candidate_in_container",
        lambda code, condition, **kwargs: {"status": "evaluated", "condition": condition},
    )

    report = run_reviewed_proposals(
        project_root,
        human_reviewed=True,
        proposals_directory=proposal_directory,
        output_path=tmp_path / "comparison.json",
    )

    result = report["conditions"]["source_only"]
    assert result["status"] == "evaluated"
    assert result["prompt_sha256"] == result["expected_prompt_sha256"]
    assert result["sandbox"]["human_review_declared"] is True
    assert result["sandbox"]["agent_review_declared"] is False
    assert report["reviewer"] == "human"


def test_agent_review_is_recorded_without_claiming_human_inspection(tmp_path, monkeypatch):
    project_root = Path(__file__).parents[1]
    proposal_directory = tmp_path / "proposals"
    record = load_eer(project_root / "artifacts" / "evaluation" / "guidance_eer.json")
    request = build_reconstruction_request(record, "source_only", source_root=project_root)
    prompt_digest = hashlib.sha256(build_reconstruction_prompt(request).encode("utf-8")).hexdigest()
    _write_proposal(proposal_directory, "source_only", prompt_digest)
    monkeypatch.setattr(
        "legacylift.evaluation.reviewed.run_candidate_in_container",
        lambda code, condition, **kwargs: {"status": "evaluated", "condition": condition},
    )

    report = run_reviewed_proposals(
        project_root,
        agent_reviewed=True,
        proposals_directory=proposal_directory,
        output_path=tmp_path / "comparison.json",
    )

    sandbox = report["conditions"]["source_only"]["sandbox"]
    assert report["reviewer"] == "agent"
    assert sandbox["reviewer"] == "agent"
    assert sandbox["human_review_declared"] is False
    assert sandbox["agent_review_declared"] is True


@pytest.mark.parametrize("candidate_failure", [True, False])
def test_candidate_failures_are_results_but_infrastructure_failures_keep_run_incomplete(
    tmp_path, monkeypatch, candidate_failure
):
    project_root = Path(__file__).parents[1]
    proposal_directory = tmp_path / "proposals"
    record = load_eer(project_root / "artifacts" / "evaluation" / "guidance_eer.json")
    for condition in ("source_only", "runtime_only", "hybrid"):
        request = build_reconstruction_request(record, condition, source_root=project_root)
        digest = hashlib.sha256(build_reconstruction_prompt(request).encode()).hexdigest()
        _write_proposal(proposal_directory, condition, digest)

    def fail_run(*args, **kwargs):
        if candidate_failure:
            raise CandidateExecutionError("ModuleNotFoundError", "missing candidate module")
        raise RuntimeError("Docker daemon unavailable")

    monkeypatch.setattr("legacylift.evaluation.reviewed.run_candidate_in_container", fail_run)
    report = run_reviewed_proposals(
        project_root,
        agent_reviewed=True,
        proposals_directory=proposal_directory,
        output_path=tmp_path / "comparison.json",
    )

    assert report["functional_evaluation_complete"] is False
    assert report["status"] == (
        "completed_with_candidate_failures" if candidate_failure else "incomplete"
    )
    for metrics in report["experiment_metrics"].values():
        assert metrics["planned_step_count"] == 6
        assert metrics["functional_metrics_available"] is False
        assert metrics["operational_step_pass_rate"] == (0.0 if candidate_failure else None)


@pytest.mark.skipif(
    os.environ.get("LEGACYLIFT_DOCKER_SMOKE") != "1",
    reason="Docker integration requires LEGACYLIFT_DOCKER_SMOKE=1",
)
def test_reviewed_candidate_runs_in_restricted_docker_container():
    if shutil.which("docker") is None:
        pytest.fail("Docker smoke test requested but the Docker CLI is unavailable")
    info = subprocess.run(["docker", "info"], capture_output=True, check=False, timeout=30)
    if info.returncode:
        pytest.fail("Docker smoke test requested but the Docker daemon is unavailable")
    image = subprocess.run(
        ["docker", "image", "inspect", EVALUATION_IMAGE],
        capture_output=True,
        check=False,
        timeout=30,
    )
    if image.returncode:
        pytest.fail("Build Dockerfile.evaluation before running the Docker smoke test")

    source = (Path(__file__).parent / "fixtures" / "baseline_candidate.py").read_text(
        encoding="utf-8"
    )
    report = run_candidate_in_container(source, "hybrid")

    assert report["passed"] is True
    assert report["scenario_count"] == 3
    assert report["step_count"] == 6
