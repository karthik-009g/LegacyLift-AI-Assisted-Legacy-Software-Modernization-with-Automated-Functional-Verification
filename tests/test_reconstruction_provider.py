from __future__ import annotations

from pathlib import Path

from legacylift.evidence.storage import load_eer
from legacylift.reconstruction import DeterministicMockProvider, build_reconstruction_request
from legacylift.reconstruction.prompts import build_reconstruction_prompt


def current_eer():
    return load_eer(
        Path(__file__).parents[1] / "artifacts" / "evidence" / "ticket_workflows.eer.json"
    )


def test_reconstruction_conditions_filter_evidence_and_bound_source_context():
    record = current_eer()
    source_only = build_reconstruction_request(
        record, "source_only", source_root=Path(__file__).parents[1]
    )
    runtime_only = build_reconstruction_request(
        record, "runtime_only", source_root=Path(__file__).parents[1]
    )
    hybrid = build_reconstruction_request(
        record,
        "hybrid",
        source_root=Path(__file__).parents[1],
        max_source_chars=100,
        max_contracts=2,
    )

    assert source_only.facts and source_only.source_excerpt
    assert source_only.contracts == []
    assert runtime_only.facts and runtime_only.contracts
    assert runtime_only.source_excerpt == ""
    assert hybrid.source_excerpt
    assert len(hybrid.source_excerpt) <= 100
    assert len(hybrid.contracts) == 2


def test_mock_provider_is_deterministic_offline_and_never_returns_code():
    request = build_reconstruction_request(
        current_eer(), "hybrid", source_root=Path(__file__).parents[1]
    )
    provider = DeterministicMockProvider()

    first = provider.propose(request)
    second = provider.propose(request)
    prompt = build_reconstruction_prompt(request)

    assert first == second
    assert first.provider == "deterministic-mock"
    assert first.proposed_code is None
    assert first.requires_human_review is True
    assert "Do not execute generated code" in prompt
    assert len(prompt) < 20_000
