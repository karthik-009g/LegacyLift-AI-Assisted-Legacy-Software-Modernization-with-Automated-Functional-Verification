"""Typed requests and proposals shared by reconstruction providers."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EvidenceCondition = Literal["source_only", "runtime_only", "hybrid"]


class ReconstructionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    condition: EvidenceCondition
    facts: list[dict[str, Any]]
    inferences: list[dict[str, Any]]
    unknowns: list[dict[str, Any]]
    contracts: list[dict[str, Any]]
    source_excerpt: str
    limitations: list[str]
    omitted_evidence_ids: list[str] = Field(default_factory=list)
    source_excerpt_truncated: bool = False


class ProposalDerivation(BaseModel):
    """Changes to a saved model draft, distinct from original model output."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["agent_compatibility_repair"]
    parent_candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    changes: list[str] = Field(min_length=1)


class ReconstructionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    condition: EvidenceCondition
    summary: str
    evidence_ids: list[str]
    proposed_code: str | None = None
    requires_human_review: bool = True
    omitted_evidence_ids: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    model: str | None = None
    request_id: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    prompt_sha256: str | None = None
    provider_attempts: list[str] = Field(default_factory=list)
    derivation: ProposalDerivation | None = None
