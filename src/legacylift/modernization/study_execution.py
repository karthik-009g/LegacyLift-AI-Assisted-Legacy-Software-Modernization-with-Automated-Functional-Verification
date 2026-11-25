"""Serial, restartable execution of a frozen study with no implicit provider retries."""

from __future__ import annotations

import json
import os
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

from .call_ledger import CallLedger
from .contracts import canonical_hash
from .controlled_study import _binding, audit_study_plan
from .pipeline import finalize, migrate
from .study import write_json


@contextmanager
def _exclusive_runner(path: Path):
    """An OS lock is released on process exit; a leftover file never blocks resumption."""
    if path.is_symlink():
        raise ValueError("study lock must not be a symbolic link")
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if not handle.tell():
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError("another runner is executing this study") from error
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _run_directory(workspace: Path, run_id: str) -> Path:
    directory = workspace / "runs" / run_id
    if (
        (workspace / "runs").is_symlink()
        or directory.is_symlink()
        or not directory.resolve().is_relative_to(workspace.resolve())
    ):
        raise ValueError("study run escaped its workspace")
    return directory


def _result(workspace: Path, run_id: str) -> dict:
    path = _run_directory(workspace, run_id) / "result.json"
    if path.is_symlink():
        raise ValueError("trial result must not be a symbolic link")
    result = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(result, dict):
        raise ValueError("trial result must be an object")
    return result


def _artifacts(workspace: Path, run_id: str) -> dict[str, str]:
    directory = _run_directory(workspace, run_id)
    checksums = {}
    for path in sorted(directory.iterdir()):
        if path.suffix not in {".json", ".jsonl", ".py"}:
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("study result artifact must be a regular file")
        # Text normalization tolerates a checkout's line endings; content stays bound.
        checksums[path.name] = canonical_hash(path.read_text(encoding="utf-8"))
    if "result.json" not in checksums:
        raise ValueError("study trial has no durable result")
    return checksums


def _load_state(workspace: Path, directory: Path, plan: dict) -> dict:
    path = directory / "execution.json"
    if path.is_symlink():
        raise ValueError("study execution record must not be a symbolic link")
    if not path.exists():
        return {
            "version": 1,
            "study_id": plan["study_id"],
            "manifest_sha256": plan["manifest_sha256"],
            "records": [],
            "in_progress": None,
        }
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict):
        raise ValueError("study execution must be an object")
    if (
        state.get("version") != 1
        or state.get("study_id") != plan["study_id"]
        or state.get("manifest_sha256") != plan["manifest_sha256"]
        or not isinstance(state.get("records"), list)
        or len(state["records"]) > len(plan["cells"])
    ):
        raise ValueError("study execution differs from its immutable plan")
    for index, record in enumerate(state["records"]):
        cell = plan["cells"][index]
        expected = _trial_record(workspace, plan, cell, _result(workspace, cell["run_id"]))
        if record != expected:
            raise ValueError("recorded trial order, content or artifacts changed")
    pending = state.get("in_progress")
    next_index = len(state["records"])
    if pending is not None and (
        next_index >= len(plan["cells"]) or pending != plan["cells"][next_index]["run_id"]
    ):
        raise ValueError("interrupted trial differs from the next planned cell")
    return state


def _trial_record(workspace: Path, plan: dict, cell: dict, result: dict) -> dict:
    binding = _binding(plan, cell)
    if (
        result.get("run_id") != cell["run_id"]
        or any(result.get(key) != value for key, value in binding.items())
        or result.get("seeded_from_run_id")
    ):
        raise ValueError("trial result differs from planned identity, scope or provider")
    CallLedger(workspace).validate_existing(cell["run_id"], binding, seeded=False)
    attempts = result.get("attempts", [])
    if (
        result.get("status")
        not in {
            "passed",
            "compatibility_failed",
            "static_review_blocked",
            "candidate_boot_failed",
            "runtime_failed",
            "provider_paused",
            "provider_failed",
        }
        or not isinstance(attempts, list)
        or any(not isinstance(attempt, dict) for attempt in attempts)
    ):
        raise ValueError("trial result has invalid status or candidate history")
    if any(
        attempt.get("provenance", {}).get("provider") != plan["provider"]
        or attempt.get("provenance", {}).get("model") != plan["model"]
        for attempt in attempts
    ):
        raise ValueError("candidate provenance differs from the fixed provider/model")
    last = attempts[-1] if attempts else {}
    if result["status"] == "passed":
        source_path = _run_directory(workspace, cell["run_id"]) / "app.py"
        if source_path.is_symlink():
            raise ValueError("candidate source must not be a symbolic link")
        if (
            type(last.get("scenario_count")) is not int
            or last["scenario_count"] != 6
            or type(last.get("passed_count")) is not int
            or last["passed_count"] != 6
            or canonical_hash(source_path.read_text(encoding="utf-8")) != last.get("source_sha256")
        ):
            raise ValueError("trial guidance pass is not bound to its candidate")
    if result.get("held_out_evaluated"):
        path = _run_directory(workspace, cell["run_id"]) / "held-out.json"
        if path.is_symlink():
            raise ValueError("held-out report must not be a symbolic link")
        held_out = json.loads(path.read_text(encoding="utf-8"))
        if (
            result["status"] != "passed"
            or canonical_hash(held_out) != result.get("held_out_report_sha256")
            or held_out.get("source_sha256") != last.get("source_sha256")
            or held_out.get("status") != result.get("held_out_status")
            or held_out.get("passed_count") != result.get("held_out_passed_count")
            or held_out.get("scenario_count") != result.get("held_out_scenario_count")
            or type(held_out.get("scenario_count")) is not int
            or held_out["scenario_count"] != 4
            or type(held_out.get("passed_count")) is not int
            or not 0 <= held_out["passed_count"] <= 4
            or (held_out.get("status") == "passed") != (held_out["passed_count"] == 4)
        ):
            raise ValueError("trial held-out summary differs from its bound report")
    usage = CallLedger(workspace).summary(cell["run_id"])
    reported_tokens = []
    for attempt in attempts:
        tokens = attempt.get("provenance", {}).get("usage", {})
        total = tokens.get("total_tokens", tokens.get("totalTokenCount"))
        if type(total) is int and total >= 0:
            reported_tokens.append(total)
    record = {
        "cell": cell,
        "status": result["status"],
        "failure_category": result.get("failure", {}).get("category"),
        "guidance_passed": result["status"] == "passed",
        "guidance_passed_count": last.get("passed_count"),
        "guidance_scenario_count": last.get("scenario_count"),
        "held_out_evaluated": result.get("held_out_evaluated", False),
        "held_out_status": result.get("held_out_status"),
        "held_out_passed_count": result.get("held_out_passed_count"),
        "held_out_scenario_count": result.get("held_out_scenario_count"),
        "workflow_passed": result["status"] == "passed"
        and result.get("held_out_evaluated") is True
        and result.get("held_out_status") == "passed",
        "requests_consumed": usage["legacy_requests_consumed"] + usage["reserved_requests"],
        "reported_tokens": sum(reported_tokens),
        "requests_without_token_usage": max(0, usage["reserved_requests"] - len(reported_tokens)),
        "security_verdict": "not_assessed",
        "artifacts": _artifacts(workspace, cell["run_id"]),
    }
    record["record_sha256"] = canonical_hash(record)
    return record


def _report(plan: dict, state: dict, protocol: dict) -> dict:
    records = state["records"]
    return {
        "study_id": plan["study_id"],
        "state": "completed" if len(records) == len(plan["cells"]) else "incomplete",
        "planned_trials": len(plan["cells"]),
        "recorded_trials": len(records),
        "next_run_id": plan["cells"][len(records)]["run_id"]
        if len(records) < len(plan["cells"])
        else None,
        "in_progress": state["in_progress"],
        "requests_consumed": protocol["requests_consumed"],
        "maximum_http_requests": protocol["maximum_http_requests"],
        "guidance_passing_trials": sum(record["guidance_passed"] for record in records),
        "held_out_evaluated_trials": sum(record["held_out_evaluated"] for record in records),
        "workflow_passing_trials": sum(record["workflow_passed"] for record in records),
        "reported_tokens": sum(record["reported_tokens"] for record in records),
        "requests_without_token_usage": protocol["requests_consumed"]
        - sum(
            record["requests_consumed"] - record["requests_without_token_usage"]
            for record in records
        ),
        "security_verdict": "not_assessed",
        "outcome_counts": dict(Counter(record["status"] for record in records)),
        "condition_counts": {
            condition: {
                "planned": sum(cell["condition"] == condition for cell in plan["cells"]),
                "recorded": sum(record["cell"]["condition"] == condition for record in records),
                "workflow_passed": sum(
                    record["workflow_passed"]
                    for record in records
                    if record["cell"]["condition"] == condition
                ),
            }
            for condition in ("source_only", "runtime_only", "hybrid")
        },
        "records": records,
        "limitations": [
            "Incomplete studies do not establish evidence-condition superiority.",
            "Reported token usage excludes unknown usage from failed or interrupted requests.",
            "Local checksums are consistency checks under trusted-controller ownership.",
            "Compatibility is separate from security assessment and human source approval.",
        ],
    }


def study_report(workspace: Path, study_id: str) -> dict:
    protocol = audit_study_plan(workspace, study_id)
    directory = workspace / "experiments" / study_id
    plan = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    with _exclusive_runner(directory / "runner.lock"):
        return _report(plan, _load_state(workspace, directory, plan), protocol)


def run_study(workspace: Path, study_id: str, *, max_trials: int = 1, checkpoint=lambda *a: None):
    if type(max_trials) is not int or not 1 <= max_trials <= 27:
        raise ValueError("max_trials must be between one and 27")
    audit_study_plan(workspace, study_id)  # Validate ID/path/inputs before opening a lock.
    directory = workspace / "experiments" / study_id
    with _exclusive_runner(directory / "runner.lock"):
        protocol = audit_study_plan(workspace, study_id)
        plan = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        state = _load_state(workspace, directory, plan)
        destination = directory / "execution.json"
        stop_reason = None
        for _ in range(max_trials):
            index = len(state["records"])
            if index == len(plan["cells"]):
                break
            cell = plan["cells"][index]
            state["in_progress"] = cell["run_id"]
            write_json(destination, state)
            checkpoint(f"Controlled trial {index + 1}/{len(plan['cells'])}", index / 27)
            result_path = _run_directory(workspace, cell["run_id"]) / "result.json"
            try:
                if result_path.exists():
                    # A durable result after a controller crash is reused, never regenerated.
                    result = _result(workspace, cell["run_id"])
                else:
                    result = migrate(
                        workspace,
                        workflow=cell["workflow"],
                        condition=cell["condition"],
                        provider=plan["provider"],
                        max_repairs=plan["max_repairs_per_trial"],
                        run_id=cell["run_id"],
                        checkpoint=checkpoint,
                    )
                record = _trial_record(workspace, plan, cell, result)
                if result["status"] == "passed" and not result.get("held_out_evaluated"):
                    finalize(workspace, cell["run_id"], checkpoint)
                    result = _result(workspace, cell["run_id"])
                    record = _trial_record(workspace, plan, cell, result)
            except (OSError, RuntimeError, ValueError) as error:
                # Retain the in-progress ID. Pipeline resumption detects uncertain call
                # intents and never resends them without explicit opt-in (not used here).
                state["last_interruption"] = {"error_type": type(error).__name__}
                write_json(destination, state)
                stop_reason = "controller_interrupted"
                break
            state["records"].append(record)
            state["in_progress"] = None
            state.pop("last_interruption", None)
            write_json(destination, state)
            if result["status"] in {"provider_failed", "provider_paused", "runtime_failed"}:
                stop_reason = result["status"]
                break
        protocol = audit_study_plan(workspace, study_id)
        report = _report(plan, state, protocol)
        report["stop_reason"] = stop_reason
        write_json(directory / "report.json", report)
        return report
