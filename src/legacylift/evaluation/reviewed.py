"""Host-side orchestration for reviewed proposals and restricted Docker runs."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from legacylift.evidence.storage import load_eer
from legacylift.reconstruction.context import (
    DEFAULT_MAX_CONTEXT_CHARS,
    DEFAULT_MAX_CONTRACTS,
    DEFAULT_MAX_SOURCE_CHARS,
    build_reconstruction_request,
)
from legacylift.reconstruction.models import EvidenceCondition, ReconstructionProposal
from legacylift.reconstruction.prompts import build_reconstruction_prompt
from legacylift.runtime_capture.scenarios import DEFAULT_SCENARIOS

from .plan import split_scenarios

CONDITIONS: tuple[EvidenceCondition, ...] = ("source_only", "runtime_only", "hybrid")
EVALUATION_IMAGE = "legacylift-evaluation:py311"
DEFAULT_PROPOSALS = Path("artifacts/proposals")
DEFAULT_REPORT = DEFAULT_PROPOSALS / "model_generated_comparison.json"
EVALUATION_SCHEMA_VERSION = "1.2"


class CandidateExecutionError(RuntimeError):
    """A reviewed candidate failed inside the evaluator, rather than Docker being unavailable."""

    def __init__(self, error_type: str, detail: str) -> None:
        self.error_type = error_type
        super().__init__(f"candidate evaluation failed: {error_type}: {detail[:500]}")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _expected_prompt_sha256(project_root: Path, condition: EvidenceCondition) -> str:
    evidence_path = project_root / "artifacts" / "evaluation" / "guidance_eer.json"
    record = load_eer(evidence_path)
    request = build_reconstruction_request(
        record,
        condition,
        source_root=project_root,
        max_source_chars=DEFAULT_MAX_SOURCE_CHARS,
        max_contracts=DEFAULT_MAX_CONTRACTS,
        max_context_chars=DEFAULT_MAX_CONTEXT_CHARS,
    )
    prompt = build_reconstruction_prompt(request)
    return _sha256(prompt.encode("utf-8"))


def run_candidate_in_container(
    code: str,
    condition: EvidenceCondition,
    *,
    image: str = EVALUATION_IMAGE,
    timeout: float = 180.0,
    docker_executable: str = "docker",
) -> dict[str, Any]:
    """Run a candidate with no network, no host secrets, and a read-only root image."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", image):
        raise ValueError("Docker image name contains unsupported characters")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    with tempfile.TemporaryDirectory(prefix="legacylift-reviewed-") as temporary_directory:
        candidate_path = Path(temporary_directory) / "candidate.py"
        candidate_path.write_text(code, encoding="utf-8")
        container_name = f"legacylift-eval-{uuid.uuid4().hex[:12]}"
        command = [
            docker_executable,
            "run",
            "--rm",
            "--name",
            container_name,
            "--network=none",
            "--read-only",
            "--memory=512m",
            "--cpus=1",
            "--pids-limit=64",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--user=65534:65534",
            "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=64m",
            "--mount",
            f"type=bind,source={candidate_path},target=/candidate.py,readonly",
            image,
            "--candidate-code",
            "/candidate.py",
            "--condition",
            condition,
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError as error:
            raise RuntimeError("Docker CLI was not found; install Docker Desktop first") from error
        except subprocess.TimeoutExpired as error:
            for cleanup_command in (
                [docker_executable, "kill", container_name],
                [docker_executable, "rm", "--force", container_name],
            ):
                try:
                    subprocess.run(
                        cleanup_command,
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    pass
            raise RuntimeError(
                f"container command exceeded the {timeout:g}-second time limit; "
                "candidate execution state is unresolved"
            ) from error

    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = None
    if isinstance(report, dict) and report.get("status") == "execution_failed":
        raise CandidateExecutionError(
            str(report.get("error_type", "unknown error")),
            str(report.get("error", "no details")),
        )
    if result.returncode:
        detail = result.stderr.strip()[-1000:] or result.stdout.strip()[-1000:]
        raise RuntimeError(f"candidate container failed ({result.returncode}): {detail}")
    if not isinstance(report, dict):
        raise RuntimeError("candidate container did not return a JSON report object")
    if report.get("status") != "evaluated":
        raise RuntimeError(
            f"candidate evaluation failed: {report.get('error_type', 'unknown error')}: "
            f"{report.get('error', 'no details')}"
        )
    return report


def run_reviewed_proposals(
    project_root: str | Path,
    *,
    human_reviewed: bool = False,
    agent_reviewed: bool = False,
    proposals_directory: str | Path = DEFAULT_PROPOSALS,
    output_path: str | Path = DEFAULT_REPORT,
    image: str = EVALUATION_IMAGE,
    timeout: float = 180.0,
) -> dict[str, Any]:
    """Evaluate current-prompt proposals after declaring who reviewed their source."""
    if human_reviewed == agent_reviewed:
        raise ValueError(
            "pass exactly one of --human-reviewed or --agent-reviewed after inspecting "
            "each proposal's code"
        )
    reviewer = "human" if human_reviewed else "agent"
    root = Path(project_root).resolve()
    proposal_root = Path(proposals_directory)
    if not proposal_root.is_absolute():
        proposal_root = root / proposal_root
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output

    results: dict[str, dict[str, Any]] = {}
    for condition in CONDITIONS:
        proposal_path = proposal_root / f"{condition}.json"
        if not proposal_path.is_file():
            results[condition] = {"status": "missing_proposal"}
            continue
        try:
            proposal = ReconstructionProposal.model_validate_json(
                proposal_path.read_text(encoding="utf-8")
            )
        except (ValueError, OSError) as error:
            results[condition] = {
                "status": "invalid_proposal",
                "error": str(error)[:500],
            }
            continue

        code = proposal.proposed_code
        if proposal.condition != condition:
            results[condition] = {"status": "condition_mismatch"}
            continue
        if not proposal.requires_human_review:
            results[condition] = {"status": "review_flag_missing"}
            continue
        if not code or not code.strip():
            results[condition] = {"status": "no_code_generated"}
            continue

        code_digest = _sha256(code.encode("utf-8"))
        proposal_metadata = {
            "provider": proposal.provider,
            "provider_attempts": proposal.provider_attempts,
            "candidate_origin": "agent_repaired_model_output"
            if proposal.derivation
            else "raw_model_output",
            "derivation": proposal.derivation.model_dump(mode="json")
            if proposal.derivation
            else None,
            "model": proposal.model,
            "request_id": proposal.request_id,
            "prompt_sha256": proposal.prompt_sha256,
            "candidate_sha256": code_digest,
            "usage": proposal.usage,
        }
        if not proposal.prompt_sha256:
            results[condition] = {
                **proposal_metadata,
                "status": "prompt_hash_missing",
            }
            continue
        try:
            expected_prompt_digest = _expected_prompt_sha256(root, condition)
        except (OSError, ValueError) as error:
            results[condition] = {
                **proposal_metadata,
                "status": "prompt_context_unavailable",
                "error": str(error)[:500],
            }
            continue
        if proposal.prompt_sha256 != expected_prompt_digest:
            results[condition] = {
                **proposal_metadata,
                "status": "stale_prompt",
                "expected_prompt_sha256": expected_prompt_digest,
            }
            continue

        sandbox = {
            "runtime": "docker",
            "image": image,
            "network": "disabled",
            "root_filesystem": "read_only",
            "host_api_key_passed": False,
            "human_review_declared": human_reviewed,
            "agent_review_declared": agent_reviewed,
            "reviewer": reviewer,
        }
        try:
            evaluated = run_candidate_in_container(
                code,
                condition,
                image=image,
                timeout=timeout,
            )
        except (OSError, RuntimeError, ValueError) as error:
            results[condition] = {
                **proposal_metadata,
                "status": "evaluation_failed",
                "expected_prompt_sha256": expected_prompt_digest,
                "sandbox": sandbox,
                "failure_category": "candidate"
                if isinstance(error, CandidateExecutionError)
                else "infrastructure_or_runner",
                "error": str(error)[:1000],
            }
            continue
        sandbox_details = evaluated.pop("sandbox", {})
        results[condition] = {
            **evaluated,
            **proposal_metadata,
            "expected_prompt_sha256": expected_prompt_digest,
            "unsupported_behavior_or_claim_count": {
                "status": "partially_measured",
                "reported_unsupported_claim_count": len(proposal.unsupported_claims),
                "reported_claims": proposal.unsupported_claims,
                "unsupported_behavior_count": None,
                "reason": (
                    "Claims are self-reported by the model; differential mismatches are not "
                    "classified by cause or supportability."
                ),
            },
            "sandbox": {
                **sandbox_details,
                **sandbox,
            },
        }

    completed = all(results[condition].get("status") == "evaluated" for condition in CONDITIONS)
    terminal = all(
        result.get("status") == "evaluated" or result.get("failure_category") == "candidate"
        for result in results.values()
    )
    _, held_out = split_scenarios(DEFAULT_SCENARIOS)
    experiment_metrics = {}
    for condition, result in results.items():
        evaluated = result.get("status") == "evaluated"
        candidate_failed = result.get("failure_category") == "candidate"
        experiment_metrics[condition] = {
            "planned_scenario_count": len(held_out),
            "planned_step_count": sum(len(scenario.steps) for scenario in held_out),
            "candidate_execution_succeeded": True
            if evaluated
            else False
            if candidate_failed
            else None,
            "functional_metrics_available": evaluated,
            "operational_scenario_pass_rate": result.get("scenario_match_rate")
            if evaluated
            else 0.0
            if candidate_failed
            else None,
            "operational_step_pass_rate": result.get("step_match_rate")
            if evaluated
            else 0.0
            if candidate_failed
            else None,
        }
    report = {
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
        "status": "completed"
        if completed
        else ("completed_with_candidate_failures" if terminal else "incomplete"),
        "functional_evaluation_complete": completed,
        "experiment_metrics": experiment_metrics,
        "operational_metric_definition": (
            "A candidate that fails inside the evaluator receives zero operational passes over "
            "the planned held-out cases; this is not a measured field-agreement score. "
            "Infrastructure failures remain unavailable and keep the experiment incomplete."
        ),
        "runtime": "docker",
        "reviewer": reviewer,
        "study": "initial_ticket_workflow_evidence_conditions",
        "scope": "held-out scenarios only",
        "conditions": results,
        "report_path": output.relative_to(root).as_posix()
        if output.is_relative_to(root)
        else str(output),
        "comparative_claims_supported": False,
        "comparison_limit": (
            "One model proposal per condition on one fixed synthetic split supports descriptive "
            "results only, not a general claim that an evidence condition is better."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report
