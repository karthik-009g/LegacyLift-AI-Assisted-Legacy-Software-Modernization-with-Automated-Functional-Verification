"""Provider protocol and a deterministic, credential-free test provider."""

from __future__ import annotations

from typing import Protocol

from .models import ReconstructionProposal, ReconstructionRequest


class ReconstructionProvider(Protocol):
    def propose(self, request: ReconstructionRequest) -> ReconstructionProposal:
        """Return a proposal without executing or grading generated code."""


class DeterministicMockProvider:
    """Offline provider used for tests and reproducible demos without API keys."""

    def propose(self, request: ReconstructionRequest) -> ReconstructionProposal:
        evidence_ids = sorted(
            {
                item[key]
                for collection, key in (
                    (request.facts, "fact_id"),
                    (request.inferences, "inference_id"),
                    (request.unknowns, "unknown_id"),
                    (request.contracts, "contract_id"),
                )
                for item in collection
            }
        )
        summary = (
            f"Offline proposal for {request.condition}: consider "
            f"{len(request.facts)} facts, {len(request.contracts)} contracts, and "
            f"{len(request.unknowns)} unresolved questions. "
            f"{len(request.omitted_evidence_ids)} evidence items were omitted by context bounds. "
            "No executable code was generated."
        )
        return ReconstructionProposal(
            provider="deterministic-mock",
            condition=request.condition,
            summary=summary,
            evidence_ids=evidence_ids,
            proposed_code=None,
            requires_human_review=True,
            omitted_evidence_ids=request.omitted_evidence_ids,
        )
