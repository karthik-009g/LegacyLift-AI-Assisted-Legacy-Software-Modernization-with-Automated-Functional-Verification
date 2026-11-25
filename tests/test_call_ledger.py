"""Request budgets survive seeded branches, process restarts and provider fallback."""

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from legacylift.modernization.call_ledger import CallBudgetExceeded, CallLedger
from legacylift.modernization.generation import generate
from legacylift.modernization.protocol import INPUT_FILES, code_hashes, input_hashes

BINDING = {
    "workflow": "read",
    "condition": "hybrid",
    "provider_policy": "groq",
    "max_repairs": 2,
    "context_sha256": "a" * 64,
}


def run_fixture(workspace, name, *, parent=None, calls=0):
    directory = workspace / "runs" / name
    directory.mkdir(parents=True, exist_ok=True)
    if parent:
        (directory / "seed.json").write_text(json.dumps({"source_run_id": parent}))
    for attempt in range(calls):
        (directory / f"call-{attempt}.json").write_text(json.dumps({"provider_policy": "groq"}))
    return directory


def test_legacy_exhausted_chain_cannot_reset_budget_through_zero_call_or_seed_branch(tmp_path):
    run_fixture(tmp_path, "root", calls=2)
    run_fixture(tmp_path, "repair", parent="root", calls=1)
    run_fixture(tmp_path, "replay", parent="repair")
    run_fixture(tmp_path, "branch", parent="root")
    ledger = CallLedger(tmp_path)
    assert ledger.register("replay", BINDING) == "root"
    assert ledger.register("branch", BINDING) == "root"
    assert ledger.summary("root")["legacy_requests_consumed"] == 3
    assert ledger.summary("root")["remaining"] == 0
    with pytest.raises(CallBudgetExceeded):
        ledger.reserve("branch", 1, "groq", "model", "b" * 64)
    assert ledger.summary("root")["reserved_requests"] == 0


def test_concurrent_reservations_across_seed_branches_never_exceed_three(tmp_path):
    run_fixture(tmp_path, "root")
    run_fixture(tmp_path, "branch", parent="root")
    ledger = CallLedger(tmp_path)
    ledger.register("root", BINDING)
    ledger.register("branch", BINDING)

    def reserve(index):
        try:
            return CallLedger(tmp_path).reserve(
                "root" if index % 2 else "branch", 0, "groq", "model", "b" * 64
            )
        except CallBudgetExceeded:
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(reserve, range(8)))
    assert len([item for item in results if item is not None]) == 3
    # Unfinished reservations count after restart, even if a response was never recorded.
    restarted = CallLedger(tmp_path)
    assert restarted.summary("root")["remaining"] == 0
    assert restarted.summary("root")["reserved_requests"] == 3


def test_model_is_fixed_across_seed_and_restart_without_blocking_other_provider(tmp_path):
    run_fixture(tmp_path, "root")
    run_fixture(tmp_path, "child", parent="root")
    binding = {**BINDING, "provider_policy": "auto"}
    ledger = CallLedger(tmp_path)
    ledger.register("root", binding)
    ledger.register("child", binding)
    ledger.reserve("root", 0, "groq", "original-model", "a" * 64)
    restarted = CallLedger(tmp_path)
    with pytest.raises(ValueError, match="model is immutable"):
        restarted.reserve("child", 1, "groq", "different-model", "b" * 64)
    assert restarted.summary("root")["remaining"] == 2
    restarted.reserve("child", 1, "groq", "original-model", "b" * 64)
    restarted.reserve("child", 1, "gemini", "backup-model", "b" * 64)
    assert restarted.summary("root")["remaining"] == 0
    assert restarted.summary_for_run("child")["remaining"] == 0


def test_bindings_manifests_and_recorded_outcomes_are_immutable_and_key_free(tmp_path):
    run_fixture(tmp_path, "root")
    ledger = CallLedger(tmp_path)
    ledger.register("root", BINDING)
    with pytest.raises(ValueError, match="immutable"):
        ledger.register("root", {**BINDING, "condition": "runtime_only"})
    with pytest.raises(ValueError, match="immutable"):
        ledger.register("root", BINDING, manifest={"root_run_id": "root", "call_limit": 4})
    request_id = ledger.reserve("root", 0, "groq", "model", "b" * 64)
    outcome = [
        {
            "provider": "groq",
            "category": "quota_exhausted",
            "http_status": 429,
            "detail": "private-key-value-must-not-be-persisted",
        }
    ]
    ledger.finish([(request_id, "groq")], outcome)
    assert "private-key-value" not in json.dumps(ledger.summary("root"))
    with pytest.raises(ValueError, match="immutable"):
        ledger.finish([(request_id, "groq")], [{"provider": "groq", "status": "generated"}])


def test_auto_fallback_reserves_each_http_request_and_stops_before_transport_when_full(
    tmp_path, monkeypatch
):
    run_fixture(tmp_path, "root")
    ledger = CallLedger(tmp_path)
    ledger.register("root", BINDING)
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-groq-key")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-gemini-key")
    reservations, requests = [], []

    def before(provider, model):
        reservations.append((ledger.reserve("root", 0, provider, model, "b" * 64), provider))

    def respond(request):
        requests.append(request.url.host)
        assert ledger.summary("root")["reserved_requests"] == len(requests)
        if request.url.host == "api.groq.com":
            return httpx.Response(503, request=request)
        output = {
            "summary": "Synthetic fixture",
            "source": "app = None\n",
            "unknowns": [],
            "evidence_ids": [],
        }
        return httpx.Response(
            200,
            request=request,
            json={
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": json.dumps(output)}]},
                    }
                ]
            },
        )

    transport = httpx.MockTransport(respond)
    _, provenance = generate(
        "fixture prompt", provider="auto", transport=transport, before_request=before
    )
    ledger.finish(reservations, provenance["attempts"])
    assert requests == ["api.groq.com", "generativelanguage.googleapis.com"]
    assert ledger.summary("root")["remaining"] == 1
    selected_model = ledger.summary("root")["requests"][0]["model"]
    ledger.reserve("root", 1, "groq", selected_model, "c" * 64)
    with pytest.raises(CallBudgetExceeded):
        generate(
            "blocked fixture prompt", provider="groq", transport=transport, before_request=before
        )
    assert len(requests) == 2


def test_controlled_manifest_fixes_provider_model_and_refuses_seed_extensions(tmp_path):
    run_fixture(tmp_path, "root")
    for relative in INPUT_FILES:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    manifest = {
        "version": 1,
        "scope": "controlled",
        "root_run_id": "root",
        "call_limit": 3,
        "provider": "groq",
        "model": "fixed-model",
        "code_sha256": code_hashes(),
        "input_sha256": input_hashes(tmp_path),
    }
    ledger = CallLedger(tmp_path)
    ledger.register("root", BINDING, manifest=manifest)
    with pytest.raises(ValueError, match="seeded diagnostics"):
        ledger.validate_existing("root", BINDING, seeded=True)
    with pytest.raises(ValueError, match="provider/model"):
        ledger.reserve("root", 0, "gemini", "fixed-model", "b" * 64)
    with pytest.raises(ValueError, match="provider/model"):
        ledger.reserve("root", 0, "groq", "another-model", "b" * 64)
    run_fixture(tmp_path, "branch", parent="root")
    with pytest.raises(ValueError, match="cannot be extended"):
        ledger.register("branch", BINDING)
    assert ledger.summary("root")["reserved_requests"] == 0


def test_seed_cycles_fail_closed_before_any_request_reservation(tmp_path):
    run_fixture(tmp_path, "a", parent="b")
    run_fixture(tmp_path, "b", parent="a")
    with pytest.raises(ValueError, match="cyclic"):
        CallLedger(tmp_path).register("a", BINDING)


def test_child_crash_after_reservation_keeps_the_request_consumed(tmp_path):
    run_fixture(tmp_path, "root")
    ledger = CallLedger(tmp_path)
    ledger.register("root", BINDING)
    script = (
        "import os,sys; from pathlib import Path; "
        "from legacylift.modernization.call_ledger import CallLedger; "
        "CallLedger(Path(sys.argv[1])).reserve('root',0,'groq','model','b'*64); os._exit(0)"
    )
    child = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True,
        timeout=20,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert child.returncode == 0
    assert CallLedger(tmp_path).summary("root")["reserved_requests"] == 1
    ledger.reserve("root", 1, "groq", "model", "b" * 64)
    ledger.reserve("root", 2, "groq", "model", "b" * 64)
    with pytest.raises(CallBudgetExceeded):
        CallLedger(tmp_path).reserve("root", 2, "groq", "model", "b" * 64)
