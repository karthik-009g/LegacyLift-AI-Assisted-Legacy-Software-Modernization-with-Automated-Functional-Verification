"""Deterministic sensitivity checks for the frozen behavior comparator."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from legacylift.runtimes.redmine import ASSETS, RedmineReference, RuntimeUnavailable

from .contracts import canonical_hash, comparable, contract_manifest, differences
from .contracts import scenarios as declared_scenarios
from .study import capture

MUTATION_TARGETS = (
    ("authorization_status", "read.outsider", "steps[0].response.status"),
    ("validation_status", "create.blank", "steps[0].response.status"),
    (
        "response_header",
        "create.basic",
        "steps[0].response.headers.content-type",
    ),
    ("empty_body_semantics", "update.advance", "steps[0].response.body_empty"),
    (
        "database_state",
        "create.basic",
        "steps[0].database_after.issues[0].subject",
    ),
    (
        "audit_effect",
        "update.advance",
        "steps[0].database_after.journals.length",
    ),
)


def _load_guidance(workspace: Path) -> tuple[dict, dict[str, dict]]:
    """Load only the guidance artifact; never open the held-out oracle file."""
    guidance = json.loads((workspace / "study/guidance.json").read_text(encoding="utf-8"))
    if guidance.get("contract") != contract_manifest():
        raise ValueError("frozen study differs from the current behavior contract")
    cases = guidance.get("scenarios")
    if not isinstance(cases, list) or any(case.get("split") != "guidance" for case in cases):
        raise ValueError("guidance artifact contains non-guidance scenarios")
    expected_ids = {
        case["scenario_id"] for case in declared_scenarios() if case.get("split") == "guidance"
    }
    by_id = {case["scenario_id"]: case for case in cases}
    if len(cases) != len(expected_ids) or set(by_id) != expected_ids:
        raise ValueError("guidance artifact does not match the frozen guidance scenario set")
    oracle_hash = guidance.get("oracle_sha256")
    if (
        not isinstance(oracle_hash, str)
        or len(oracle_hash) != 64
        or any(character not in "0123456789abcdef" for character in oracle_hash)
    ):
        raise ValueError("guidance artifact has no valid parent oracle checksum")
    return guidance, by_id


def _write_report(report: dict, output_path: Path | None) -> dict:
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = output_path.with_suffix(output_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(output_path)
    return report


def _case_mismatches(expected: dict, actual: dict) -> list[dict]:
    if len(expected["steps"]) != len(actual["steps"]):
        return [{"path": "steps.length", "reason": "length"}]
    summaries = []
    for index, (expected_step, actual_step) in enumerate(
        zip(expected["steps"], actual["steps"], strict=True)
    ):
        summaries.extend(
            {"path": item["path"], "reason": item["reason"]}
            for item in differences(
                comparable(expected_step), comparable(actual_step), path=f"steps[{index}]"
            )
        )
    return summaries


def _mutate(case: dict, mutation_id: str) -> None:
    step = case["steps"][0]
    if mutation_id == "authorization_status":
        step["response"]["status"] = 200
    elif mutation_id == "validation_status":
        step["response"]["status"] = 201
    elif mutation_id == "response_header":
        step["response"]["headers"].pop("content-type", None)
    elif mutation_id == "empty_body_semantics":
        response = step["response"]
        response["body_bytes"] = 1 if response["body_bytes"] == 0 else 0
    elif mutation_id == "database_state":
        issue = step["database_after"]["issues"][0]
        issue["subject"] = str(issue["subject"]) + " [mutation]"
    elif mutation_id == "audit_effect":
        step["database_after"]["journals"] = []
    else:
        raise ValueError(f"unsupported mutation: {mutation_id}")


def run_mutation_campaign(workspace: Path, output_path: Path | None = None) -> dict:
    """Mutate six guidance observations and require the comparator to detect each fault.

    This is a verifier sensitivity check, not an application migration or a runtime
    execution. It never reads held-out observations or sends data to a provider.
    """
    guidance_artifact, guidance = _load_guidance(workspace)

    results = []
    for mutation_id, scenario_id, expected_path in MUTATION_TARGETS:
        original = guidance.get(scenario_id)
        if not original:
            raise ValueError(f"mutation target is missing from guidance: {scenario_id}")
        mutated = copy.deepcopy(original)
        _mutate(mutated, mutation_id)
        mismatches = []
        for index, (expected_step, actual_step) in enumerate(
            zip(original["steps"], mutated["steps"], strict=True)
        ):
            mismatches.extend(
                differences(
                    comparable(expected_step),
                    comparable(actual_step),
                    path=f"steps[{index}]",
                )
            )
        paths = sorted({item["path"] for item in mismatches})
        results.append(
            {
                "mutation_id": mutation_id,
                "scenario_id": scenario_id,
                "expected_mismatch_path": expected_path,
                "detected": expected_path in paths,
                "mismatch_paths": paths,
            }
        )

    detected = sum(item["detected"] for item in results)
    report = {
        "status": "passed" if detected == len(MUTATION_TARGETS) else "failed",
        "scope": "guidance_comparator_sensitivity_only",
        "oracle_sha256": guidance_artifact["oracle_sha256"],
        "guidance_sha256": canonical_hash(guidance_artifact["scenarios"]),
        "guidance_scenarios_available": len(guidance),
        "mutation_count": len(results),
        "detected_count": detected,
        "results": results,
        "runtime_execution": False,
        "model_requests": 0,
        "held_out_read": False,
    }
    return _write_report(report, output_path)


class _ObservationFault:
    """Inject one controlled fault at the trusted runtime adapter boundary."""

    def __init__(self, runtime, mutation_id: str) -> None:
        self.runtime = runtime
        self.mutation_id = mutation_id
        self.snapshot_count = 0

    def reset(self) -> None:
        self.snapshot_count = 0
        self.runtime.reset()

    def request(self, request):
        response = self.runtime.request(request)
        if self.mutation_id == "authorization_status":
            return response.model_copy(update={"status": 200})
        if self.mutation_id == "validation_status":
            return response.model_copy(update={"status": 201})
        if self.mutation_id == "response_header":
            headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() != "content-type"
            }
            return response.model_copy(update={"headers": headers})
        if self.mutation_id == "empty_body_semantics":
            return response.model_copy(update={"body_bytes": 1 if response.body_bytes == 0 else 0})
        return response

    def snapshot(self) -> dict:
        snapshot = copy.deepcopy(self.runtime.snapshot())
        self.snapshot_count += 1
        if self.snapshot_count != 2:
            return snapshot
        if self.mutation_id == "database_state":
            if not snapshot.get("issues"):
                raise ValueError("database-state mutation target has no issue row")
            snapshot["issues"][0]["subject"] = str(snapshot["issues"][0]["subject"]) + " [mutation]"
        elif self.mutation_id == "audit_effect":
            snapshot["journals"] = []
        return snapshot


def run_runtime_mutation_campaign(
    workspace: Path,
    output_path: Path | None = None,
    *,
    reference_factory=RedmineReference,
    checkpoint=lambda *args: None,
) -> dict:
    """Replay the real reference, then inject faults at its observation boundary.

    This validates the external runtime capture and comparison path. It is not a
    mutation of Redmine's source or a test of model-generated candidate code.
    Only guidance observations are opened; a mismatching baseline aborts injections.
    """
    guidance_artifact, guidance = _load_guidance(workspace)
    target_ids = list(dict.fromkeys(item[1] for item in MUTATION_TARGETS))
    target_cases = [guidance[scenario_id] for scenario_id in target_ids]
    try:
        with reference_factory() as reference:
            runtime_info = reference.describe()
            baseline = capture(reference, target_cases, checkpoint)
            baseline_by_id = {case["scenario_id"]: case for case in baseline}
            baseline_results = []
            for expected in target_cases:
                actual = baseline_by_id[expected["scenario_id"]]
                mismatches = _case_mismatches(expected, actual)
                baseline_results.append(
                    {
                        "scenario_id": expected["scenario_id"],
                        "matched": not mismatches,
                        "mismatches": mismatches,
                    }
                )

            baseline_passed = all(item["matched"] for item in baseline_results)
            mutation_results = []
            if baseline_passed:
                for mutation_id, scenario_id, expected_path in MUTATION_TARGETS:
                    checkpoint(f"Injecting {mutation_id}", 0.5)
                    actual = capture(
                        _ObservationFault(reference, mutation_id),
                        [guidance[scenario_id]],
                        checkpoint,
                    )[0]
                    mismatches = _case_mismatches(guidance[scenario_id], actual)
                    paths = sorted({item["path"] for item in mismatches})
                    mutation_results.append(
                        {
                            "mutation_id": mutation_id,
                            "scenario_id": scenario_id,
                            "expected_mismatch_path": expected_path,
                            "detected": expected_path in paths,
                            "mismatches": mismatches,
                        }
                    )

        detected = sum(item["detected"] for item in mutation_results)
        status = (
            "baseline_mismatch"
            if not baseline_passed
            else "passed"
            if detected == len(MUTATION_TARGETS)
            else "failed"
        )
        report = {
            "status": status,
            "scope": "pinned_redmine_reference_runtime_observation_fault_injection",
            "oracle_sha256": guidance_artifact["oracle_sha256"],
            "guidance_sha256": canonical_hash(guidance_artifact["scenarios"]),
            "baseline_scenario_count": len(baseline_results),
            "baseline_passed_count": sum(item["matched"] for item in baseline_results),
            "baseline_results": baseline_results,
            "baseline_capture_sha256": canonical_hash(baseline),
            "mutation_count": len(mutation_results),
            "detected_count": detected,
            "results": mutation_results,
            "reference": {
                key: runtime_info.get(key)
                for key in (
                    "profile",
                    "image",
                    "source_commit",
                    "network",
                    "read_only_root",
                    "user",
                    "host_api_keys_passed",
                )
            },
            "runtime_execution": True,
            "model_requests": 0,
            "held_out_read": False,
        }
    except RuntimeUnavailable as error:
        report = {
            "status": "infrastructure_failed",
            "scope": "pinned_redmine_reference_runtime_observation_fault_injection",
            "oracle_sha256": guidance_artifact["oracle_sha256"],
            "guidance_sha256": canonical_hash(guidance_artifact["scenarios"]),
            "infrastructure_error": type(error).__name__,
            "message": str(error)[:500],
            "runtime_execution": False,
            "model_requests": 0,
            "held_out_read": False,
        }
    return _write_report(report, output_path)


def _candidate_source_mutations(source: str) -> list[tuple[str, str, str, str]]:
    """Create isolated source faults across the engineered create/update/read fixture."""
    variants = []

    def replace_once(mutation_id, scenario_id, expected_path, old, new):
        if source.count(old) != 1:
            raise ValueError(f"controlled candidate mutation anchor is not unique: {mutation_id}")
        variants.append((mutation_id, scenario_id, expected_path, source.replace(old, new, 1)))

    replace_once(
        "authorization_status",
        "read.outsider",
        "steps[0].response.status",
        'content=b"",\n                status_code=403,',
        'content=b"",\n                status_code=200,',
    )
    replace_once(
        "validation_status",
        "create.blank",
        "steps[0].response.status",
        "status_code=422",
        "status_code=201",
    )
    replace_once(
        "response_header",
        "create.blank",
        "steps[0].response.headers.content-type",
        '                "Content-Type": "application/json; charset=utf-8",',
        '                "Content-Type": "text/plain",',
    )
    replace_once(
        "empty_body_semantics",
        "read.outsider",
        "steps[0].response.body_empty",
        'content=b""',
        'content=b"x"',
    )
    replace_once(
        "create_database_state",
        "create.basic",
        "steps[0].database_after.issues[1].subject",
        "subject = str(subject)\n        # LEGACYLIFT_CREATE_STATE_FAULT_HOOK",
        'subject = str(subject) + " [mutation]"\n        # LEGACYLIFT_CREATE_STATE_FAULT_HOOK',
    )
    replace_once(
        "update_database_state",
        "update.advance",
        "steps[0].database_after.issues[0].status_id",
        "(new_status, now, issue_id),",
        "(old_status, now, issue_id),",
    )
    replace_once(
        "audit_effect",
        "update.advance",
        "steps[0].database_after.journals.length",
        "if notes is not None or status_changed:",
        "if False and (notes is not None or status_changed):",
    )
    return variants


def run_candidate_code_mutation_campaign(
    workspace: Path,
    output_path: Path | None = None,
    *,
    checkpoint=lambda *args: None,
) -> dict:
    """Run a controlled Python candidate and source-mutated variants in Docker.

    The fixture implements four guidance cases spanning denied reads, validation,
    successful issue creation, and update/audit effects. It proves that candidate source
    faults traverse the isolated Python runtime, external snapshot, and comparator path;
    it is not a model-generated or generally compatible migration.
    """
    guidance_artifact, guidance = _load_guidance(workspace)
    fixture_path = ASSETS / "controlled_mutation_candidate.py"
    source = fixture_path.read_text(encoding="utf-8")
    variants = _candidate_source_mutations(source)
    base_cases = [
        guidance["read.outsider"],
        guidance["create.blank"],
        guidance["create.basic"],
        guidance["update.advance"],
    ]
    database = (workspace / "study/fixture.sqlite3").read_bytes()
    actors = json.loads((workspace / "study/actors.private.json").read_text(encoding="utf-8"))

    from legacylift.runtimes.python_target import CandidateRejected, PythonTarget

    baseline_results = []
    mutation_results = []
    baseline_capture_hash = None
    candidate_profile = {}
    runtime_execution = False
    failure = None
    try:
        with PythonTarget(source, database, actors, timeout=180) as candidate:
            runtime_execution = True
            baseline = capture(candidate, base_cases, checkpoint)
            candidate_profile = candidate.describe()
        baseline_capture_hash = canonical_hash(baseline)
        baseline_by_id = {case["scenario_id"]: case for case in baseline}
        for expected in base_cases:
            mismatches = _case_mismatches(expected, baseline_by_id[expected["scenario_id"]])
            baseline_results.append(
                {
                    "scenario_id": expected["scenario_id"],
                    "matched": not mismatches,
                    "mismatches": mismatches,
                }
            )

        if all(item["matched"] for item in baseline_results):
            for index, (mutation_id, scenario_id, expected_path, mutated_source) in enumerate(
                variants
            ):
                checkpoint(f"Building candidate mutation {mutation_id}", 0.2 + index / 8)
                with PythonTarget(mutated_source, database, actors, timeout=180) as candidate:
                    runtime_execution = True
                    observed = capture(candidate, [guidance[scenario_id]], checkpoint)[0]
                mismatches = _case_mismatches(guidance[scenario_id], observed)
                paths = sorted({item["path"] for item in mismatches})
                mutation_results.append(
                    {
                        "mutation_id": mutation_id,
                        "scenario_id": scenario_id,
                        "expected_mismatch_path": expected_path,
                        "detected": expected_path in paths,
                        "mutated_source_sha256": canonical_hash(mutated_source),
                        "mismatches": mismatches,
                    }
                )
    except CandidateRejected as error:
        failure = {"category": "candidate_boot_failed", "message": str(error)}
    except RuntimeUnavailable as error:
        failure = {"category": "runtime_unavailable", "message": str(error)}

    message = failure.get("message", "") if failure else ""
    for token in actors.values():
        if token:
            message = message.replace(token, "[synthetic-token-redacted]")
    if failure:
        status = failure["category"]
    elif not all(item["matched"] for item in baseline_results):
        status = "baseline_mismatch"
    else:
        status = (
            "passed"
            if len(mutation_results) == len(variants)
            and all(item["detected"] for item in mutation_results)
            else "failed"
        )

    report = {
        "status": status,
        "scope": "controlled_candidate_source_mutations",
        "candidate_kind": "engineered_four_case_guidance_slice_fixture",
        "covered_scenarios": [case["scenario_id"] for case in base_cases],
        "model_generated": False,
        "oracle_sha256": guidance_artifact["oracle_sha256"],
        "guidance_sha256": canonical_hash(guidance_artifact["scenarios"]),
        "baseline_scenario_count": len(base_cases),
        "baseline_passed_count": sum(item["matched"] for item in baseline_results),
        "baseline_results": baseline_results,
        "baseline_capture_sha256": baseline_capture_hash,
        "planned_mutation_count": len(variants),
        "mutation_count": len(mutation_results),
        "detected_count": sum(item["detected"] for item in mutation_results),
        "results": mutation_results,
        "candidate_runtime": {
            key: candidate_profile.get(key)
            for key in (
                "profile",
                "base_image",
                "network",
                "read_only_root",
                "user",
                "host_api_keys_passed",
                "oracle_in_image",
            )
        }
        if candidate_profile
        else None,
        "failure": {**failure, "message": message[:500]} if failure else None,
        "runtime_execution": runtime_execution,
        "model_requests": 0,
        "held_out_read": False,
    }
    return _write_report(report, output_path)
