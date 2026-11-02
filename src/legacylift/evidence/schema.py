"""Strict Pydantic schema for facts, inferences, unknowns, contracts, and provenance."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EER_SCHEMA_VERSION = "1.0.0"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProvenanceRecord(StrictModel):
    provenance_id: str
    kind: Literal["source_ast", "runtime_trace", "analysis_limit"]
    artifact: str
    locator: str


class EvidenceFact(StrictModel):
    fact_id: str
    statement: str
    confidence: Literal["observed", "derived"]
    provenance_ids: list[str] = Field(min_length=1)


class EvidenceInference(StrictModel):
    inference_id: str
    statement: str
    rationale: str
    provenance_ids: list[str] = Field(min_length=1)


class EvidenceUnknown(StrictModel):
    unknown_id: str
    question: str
    affected_scope: str
    reason: str
    provenance_ids: list[str] = Field(min_length=1)


class WorkflowContract(StrictModel):
    contract_id: str
    workflow_id: str
    method: str
    path: str
    request_json: dict[str, Any] | None
    expected_status: int = Field(ge=100, le=599)
    expected_response_json: dict[str, Any] | list[Any] | str | int | float | bool | None
    expected_response_headers: dict[str, str]
    expected_cookies: list[dict[str, Any]]
    session_before: dict[str, Any]
    session_after: dict[str, Any]
    expected_database_delta: dict[str, Any]
    provenance_ids: list[str] = Field(min_length=1)


class ValidationCase(StrictModel):
    validation_id: str
    scenario_id: str
    step_id: str
    contract_id: str
    purpose: str
    provenance_ids: list[str] = Field(min_length=1)


class EngineeringEvidenceRecord(StrictModel):
    schema_version: Literal["1.0.0"]
    record_id: str
    scope: str
    provenance: list[ProvenanceRecord]
    observed_facts: list[EvidenceFact]
    inferences: list[EvidenceInference]
    unknowns: list[EvidenceUnknown]
    contracts: list[WorkflowContract]
    validation_cases: list[ValidationCase]
    limitations: list[str]

    @model_validator(mode="after")
    def references_resolve(self) -> EngineeringEvidenceRecord:
        provenance_ids = [item.provenance_id for item in self.provenance]
        if len(provenance_ids) != len(set(provenance_ids)):
            raise ValueError("provenance_id values must be unique")
        assertion_ids = [item.fact_id for item in self.observed_facts]
        assertion_ids.extend(item.inference_id for item in self.inferences)
        assertion_ids.extend(item.unknown_id for item in self.unknowns)
        assertion_ids.extend(item.validation_id for item in self.validation_cases)
        if len(assertion_ids) != len(set(assertion_ids)):
            raise ValueError("fact, inference, unknown, and validation identifiers must be unique")
        known_provenance = set(provenance_ids)
        contract_ids = [item.contract_id for item in self.contracts]
        if len(contract_ids) != len(set(contract_ids)):
            raise ValueError("contract_id values must be unique")
        known_contracts = set(contract_ids)

        references = [
            *self.observed_facts,
            *self.inferences,
            *self.unknowns,
            *self.contracts,
            *self.validation_cases,
        ]
        for item in references:
            missing = set(item.provenance_ids) - known_provenance
            if missing:
                raise ValueError(f"unknown provenance references: {sorted(missing)}")
        for case in self.validation_cases:
            if case.contract_id not in known_contracts:
                raise ValueError(f"unknown contract reference: {case.contract_id}")
        return self
