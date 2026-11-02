"""Combine static findings and runtime traces without erasing uncertainty."""

from __future__ import annotations

import re
from typing import Any

from legacylift.static_analysis.models import AnalysisReport

from .schema import (
    EER_SCHEMA_VERSION,
    EngineeringEvidenceRecord,
    EvidenceFact,
    EvidenceInference,
    EvidenceUnknown,
    ProvenanceRecord,
    ValidationCase,
    WorkflowContract,
)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "item"


def _step_map(trace_bundle: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (scenario["scenario_id"], step["step_id"]): step
        for scenario in trace_bundle.get("scenarios", [])
        for step in scenario.get("steps", [])
    }


def build_eer(
    analysis: AnalysisReport,
    trace_bundle: dict[str, Any],
    *,
    trace_artifact: str = "artifacts/traces/ticket_workflows.json",
    record_id: str = "legacylift-ticket-workflows-v1",
) -> EngineeringEvidenceRecord:
    """Build a versioned EER from analyzer output and a captured trace bundle."""
    provenance: list[ProvenanceRecord] = []
    facts: list[EvidenceFact] = []
    inferences: list[EvidenceInference] = []
    unknowns: list[EvidenceUnknown] = []
    contracts: list[WorkflowContract] = []
    validation_cases: list[ValidationCase] = []
    route_provenance: dict[tuple[str, str, str, int], str] = {}

    for route in analysis.routes:
        route_key = (route.method, route.path, route.function, route.line)
        provenance_id = (
            f"prov-source-{_slug(route.source_file)}-{route.line}-"
            f"{_slug(route.method + '-' + route.path + '-' + route.function)}"
        )
        route_provenance[route_key] = provenance_id
        provenance.append(
            ProvenanceRecord(
                provenance_id=provenance_id,
                kind="source_ast",
                artifact=route.source_file,
                locator=f"line {route.line}: {route.function}",
            )
        )
        facts.append(
            EvidenceFact(
                fact_id=f"fact-route-{_slug(route.method + route.path + route.function)}",
                statement=(
                    f"AST analysis found a literal {route.method} route {route.path} "
                    f"mapped to {route.function}."
                ),
                confidence="observed",
                provenance_ids=[provenance_id],
            )
        )

    for function in analysis.functions:
        if not (
            function.session_references or function.database_operations or function.branch_count
        ):
            continue
        provenance_id = (
            f"prov-source-function-{_slug(function.source_file)}-{function.line}-"
            f"{_slug(function.name)}"
        )
        provenance.append(
            ProvenanceRecord(
                provenance_id=provenance_id,
                kind="source_ast",
                artifact=function.source_file,
                locator=f"lines {function.line}-{function.end_line}: {function.name}",
            )
        )
        if function.session_references:
            facts.append(
                EvidenceFact(
                    fact_id=f"fact-session-ref-{_slug(function.source_file + function.name)}",
                    statement=f"AST analysis found a session reference in {function.name}.",
                    confidence="observed",
                    provenance_ids=[provenance_id],
                )
            )
        if function.database_operations:
            operations = ", ".join(function.database_operations)
            facts.append(
                EvidenceFact(
                    fact_id=f"fact-db-ops-{_slug(function.source_file + function.name)}",
                    statement=f"AST analysis found database calls {operations} in {function.name}.",
                    confidence="observed",
                    provenance_ids=[provenance_id],
                )
            )
        if function.branch_count:
            facts.append(
                EvidenceFact(
                    fact_id=f"fact-branches-{_slug(function.source_file + function.name)}",
                    statement=(
                        f"AST analysis counted {function.branch_count} control-flow constructs "
                        f"in {function.name}."
                    ),
                    confidence="observed",
                    provenance_ids=[provenance_id],
                )
            )

    for issue in analysis.issues:
        provenance_id = f"prov-source-issue-{_slug(issue.source_file)}-{issue.line or 0}"
        provenance.append(
            ProvenanceRecord(
                provenance_id=provenance_id,
                kind="source_ast",
                artifact=issue.source_file,
                locator=f"line {issue.line}" if issue.line else "file parse",
            )
        )
        facts.append(
            EvidenceFact(
                fact_id=f"fact-parse-issue-{_slug(issue.source_file)}-{issue.line or 0}",
                statement=f"AST analysis could not parse {issue.source_file}: {issue.message}.",
                confidence="observed",
                provenance_ids=[provenance_id],
            )
        )
        unknowns.append(
            EvidenceUnknown(
                unknown_id=f"unknown-unparsed-{_slug(issue.source_file)}-{issue.line or 0}",
                question=(
                    f"What supported structures are present in unparsed file {issue.source_file}?"
                ),
                affected_scope=issue.source_file,
                reason=(
                    "The file could not be parsed, so its route and control-flow findings "
                    "are incomplete."
                ),
                provenance_ids=[provenance_id],
            )
        )

    trace_step_provenance: dict[tuple[str, str], str] = {}
    for scenario in trace_bundle.get("scenarios", []):
        scenario_id = scenario["scenario_id"]
        for step in scenario.get("steps", []):
            step_id = step["step_id"]
            provenance_id = f"prov-trace-{_slug(scenario_id)}-{_slug(step_id)}"
            trace_step_provenance[(scenario_id, step_id)] = provenance_id
            provenance.append(
                ProvenanceRecord(
                    provenance_id=provenance_id,
                    kind="runtime_trace",
                    artifact=trace_artifact,
                    locator=f"scenario {scenario_id}, step {step_id}",
                )
            )
            request_data = step["request"]
            response_data = step["response"]
            facts.append(
                EvidenceFact(
                    fact_id=f"fact-runtime-{_slug(scenario_id)}-{_slug(step_id)}",
                    statement=(
                        f"Captured {request_data['method']} {request_data['path']} returned "
                        f"HTTP {response_data['status']} in scenario {scenario_id}."
                    ),
                    confidence="observed",
                    provenance_ids=[provenance_id],
                )
            )
            contract_id = f"contract-{_slug(scenario_id)}-{_slug(step_id)}"
            contracts.append(
                WorkflowContract(
                    contract_id=contract_id,
                    workflow_id=scenario_id,
                    method=request_data["method"],
                    path=request_data["path"],
                    request_json=request_data["json"],
                    expected_status=response_data["status"],
                    expected_response_json=response_data["json"],
                    expected_response_headers=response_data["headers"],
                    expected_cookies=response_data["cookies"],
                    session_before=step["session_before"],
                    session_after=step["session_after"],
                    expected_database_delta=step["database_delta"],
                    provenance_ids=[provenance_id],
                )
            )
            validation_cases.append(
                ValidationCase(
                    validation_id=f"validation-{_slug(scenario_id)}-{_slug(step_id)}",
                    scenario_id=scenario_id,
                    step_id=step_id,
                    contract_id=contract_id,
                    purpose=scenario["description"],
                    provenance_ids=[provenance_id],
                )
            )

    step_map = _step_map(trace_bundle)
    owned_step = step_map.get(("retrieve_owned_ticket", "get_owned_ticket"))
    other_owner_step = step_map.get(("hide_other_users_ticket", "get_unowned_ticket"))
    if owned_step and other_owner_step:
        inference_provenance = [
            trace_step_provenance[("retrieve_owned_ticket", "get_owned_ticket")],
            trace_step_provenance[("hide_other_users_ticket", "get_unowned_ticket")],
        ]
        matching_route = next(
            (
                provenance_id
                for route_key, provenance_id in route_provenance.items()
                if route_key[0] == "GET" and route_key[1] == "/tickets/<int:ticket_id>"
            ),
            None,
        )
        if matching_route is not None:
            inference_provenance.append(matching_route)
        provenance.append(
            ProvenanceRecord(
                provenance_id="prov-inference-owner-check",
                kind="runtime_trace",
                artifact="artifacts/traces/ticket_workflows.json",
                locator=(
                    "compare retrieve_owned_ticket/get_owned_ticket with "
                    "hide_other_users_ticket/get_unowned_ticket"
                ),
            )
        )
        inference_provenance.append("prov-inference-owner-check")
        if (
            owned_step["response"]["status"] != other_owner_step["response"]["status"]
            and owned_step["request"]["path"] == other_owner_step["request"]["path"]
        ):
            inferences.append(
                EvidenceInference(
                    inference_id="inference-session-ownership",
                    statement=(
                        "Ticket retrieval visibility appears to depend on the session user "
                        "for the seeded ticket."
                    ),
                    rationale=(
                        "The same retrieval path returned different statuses after the session "
                        "identity changed; this inference applies only to the captured fixture."
                    ),
                    provenance_ids=inference_provenance,
                )
            )

    limit_provenance = (
        ProvenanceRecord(
            provenance_id="prov-limit-static-analysis",
            kind="analysis_limit",
            artifact="src/legacylift/static_analysis/ast_analyzer.py",
            locator="ANALYSIS_LIMITATIONS",
        ),
        ProvenanceRecord(
            provenance_id="prov-limit-scenarios",
            kind="analysis_limit",
            artifact="src/legacylift/runtime_capture/scenarios.py",
            locator="DEFAULT_SCENARIOS",
        ),
    )
    provenance.extend(limit_provenance)
    unknowns.extend(
        (
            EvidenceUnknown(
                unknown_id="unknown-unobserved-paths",
                question="What behavior occurs on paths absent from the checked-in scenarios?",
                affected_scope="legacy ticket workflow branches outside the captured scenarios",
                reason="Runtime traces only cover the finite scenarios that were executed.",
                provenance_ids=["prov-limit-scenarios"],
            ),
            EvidenceUnknown(
                unknown_id="unknown-dynamic-python",
                question=(
                    "Are there dynamically registered routes or runtime code paths "
                    "not listed by AST analysis?"
                ),
                affected_scope="dynamic dispatch, reflection, and route registration",
                reason=(
                    "The analyzer recognizes literal Flask route decorators and does not "
                    "execute application code."
                ),
                provenance_ids=["prov-limit-static-analysis"],
            ),
        )
    )

    return EngineeringEvidenceRecord(
        schema_version=EER_SCHEMA_VERSION,
        record_id=record_id,
        scope="Selected Flask/SQLite ticket workflows in the local synthetic reference app.",
        provenance=provenance,
        observed_facts=facts,
        inferences=inferences,
        unknowns=unknowns,
        contracts=contracts,
        validation_cases=validation_cases,
        limitations=list(analysis.limitations)
        + [
            "Contracts in this record describe captured scenario steps; they are not a proof "
            "of equivalence for untested behavior.",
            "Cookie values are intentionally omitted from trace and EER artifacts.",
        ],
    )
