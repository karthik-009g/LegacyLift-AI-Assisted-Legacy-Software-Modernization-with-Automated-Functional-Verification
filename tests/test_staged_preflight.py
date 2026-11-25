"""Staged resume must not spend calls before local validation or borrow provenance."""

import json

import pytest

from legacylift.modernization import pipeline
from legacylift.modernization.call_ledger import CallLedger
from legacylift.modernization.contracts import canonical_hash
from legacylift.modernization.generation import PromptBudgetExceeded


def test_later_stage_prompt_failure_precedes_any_provider_call(tmp_path, monkeypatch):
    directory = tmp_path / "runs" / "fixture"
    directory.mkdir(parents=True)

    def prompt(context, handler):
        if handler == "create_issue":
            raise PromptBudgetExceeded("synthetic POST budget failure")
        return "GET prompt"

    monkeypatch.setattr(pipeline, "read_stage_prompt", prompt)
    monkeypatch.setattr(
        pipeline, "generate", lambda *args, **kwargs: pytest.fail("provider called")
    )
    with pytest.raises(PromptBudgetExceeded, match="POST budget"):
        pipeline._generate_read_stages(
            {},
            "parent",
            directory,
            tmp_path,
            "groq",
            None,
            [],
            lambda *args, **kwargs: pytest.fail("request reserved"),
            lambda *args: None,
        )
    assert not list(directory.iterdir())
    assert not (tmp_path / "provider-last-call.json").exists()


@pytest.mark.parametrize("mismatch", ["foreign_run", "prompt", "model", "provider"])
def test_cached_stage_rejects_unrelated_reservation_without_changing_it(
    tmp_path, monkeypatch, mismatch
):
    run_id = "currentfixture"
    directory = tmp_path / "runs" / run_id
    directory.mkdir(parents=True)
    context = {"read_generation_strategy": "staged-bodies-v3"}
    stage_prompt = "read_issue prompt"
    ledger = CallLedger(tmp_path)
    ledger.register(run_id, {})
    owner = "foreignfixture" if mismatch == "foreign_run" else run_id
    if owner != run_id:
        ledger.register(owner, {})
    request_id = ledger.reserve(
        owner,
        0,
        "gemini" if mismatch == "provider" else "groq",
        "different-model" if mismatch == "model" else "fixture-model",
        canonical_hash("unrelated prompt" if mismatch == "prompt" else stage_prompt),
    )
    original = ledger.summary_for_run(owner)
    source = "return Response(status_code=404)\n"
    record = {
        "handler": "read_issue",
        "signature": "read_issue(api_key, issue_id, include)",
        "context_sha256": canonical_hash(context),
        "prompt_sha256": canonical_hash(stage_prompt),
        "source_sha256": canonical_hash(source),
        "draft": {"source": source, "evidence_ids": [], "unknowns": []},
        "provenance": {
            "provider": "groq",
            "model": "fixture-model",
            "prompt_sha256": canonical_hash(stage_prompt),
            "request_reservations": [request_id],
            "attempts": [],
        },
    }
    path = directory / "stage-read_issue.json"
    path.write_text(json.dumps(record))
    original_cache = path.read_bytes()
    monkeypatch.setattr(pipeline, "read_stage_prompt", lambda context, handler: handler + " prompt")
    monkeypatch.setattr(
        pipeline, "generate", lambda *args, **kwargs: pytest.fail("provider called")
    )
    with pytest.raises(ValueError, match="provenance differs from its request ledger"):
        pipeline._generate_read_stages(
            context,
            "parent",
            directory,
            tmp_path,
            "groq",
            ledger,
            [],
            lambda *args, **kwargs: pytest.fail("request reserved"),
            lambda *args: None,
        )
    assert ledger.summary_for_run(owner) == original
    assert path.read_bytes() == original_cache
