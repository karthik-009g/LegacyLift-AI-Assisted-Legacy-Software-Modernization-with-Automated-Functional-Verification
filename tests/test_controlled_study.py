"""Prospective experiment design and drift checks without hidden observations or API calls."""

import json

import pytest

from legacylift.modernization import call_ledger, controlled_study
from legacylift.modernization.call_ledger import CallLedger
from legacylift.modernization.contracts import canonical_hash
from legacylift.modernization.frozen_study import seal_study


@pytest.fixture
def planned_inputs(frozen_reference_inputs, monkeypatch):
    tmp_path = frozen_reference_inputs
    (tmp_path / "evidence").mkdir()
    seal_study(tmp_path)
    (tmp_path / "evidence/redmine.json").write_text("{}")
    (tmp_path / "evidence/runtime_routes.json").write_text("{}")
    monkeypatch.setattr(
        controlled_study,
        "build_context",
        lambda workspace, workflow, condition: {
            "workflow": workflow,
            "condition": condition,
            "source": [],
            "runtime": [],
        },
    )
    return tmp_path


def test_plan_is_balanced_reproducible_key_free_and_makes_zero_requests(
    planned_inputs, monkeypatch
):
    from pathlib import Path

    original_read = Path.read_text

    def guarded(path, *args, **kwargs):
        if path.name in {"oracle.json", "held-out.json", "actors.private.json", ".env"}:
            pytest.fail("study planning opened hidden observations or credentials")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded)
    plan = controlled_study.create_study_plan(planned_inputs, provider="groq", seed=7)
    report = controlled_study.audit_study_plan(planned_inputs, plan["study_id"])
    assert report["requests_consumed"] == 0
    assert report["maximum_http_requests"] == 81
    cells = {(cell["workflow"], cell["condition"], cell["replicate"]) for cell in plan["cells"]}
    assert len(cells) == 27
    assert len({cell["run_id"] for cell in plan["cells"]}) == 27
    assert "synthetic database" not in json.dumps(plan)
    assert "private-actor-marker" not in json.dumps(plan)
    assert plan["held_out_observations_read"] is False
    again = controlled_study.create_study_plan(planned_inputs, provider="groq", seed=7)

    def order(value):
        return [(c["workflow"], c["condition"], c["replicate"]) for c in value["cells"]]

    assert order(plan) == order(again)
    with pytest.raises(ValueError, match="fixed provider"):
        controlled_study.create_study_plan(planned_inputs, provider="auto")


def test_plan_and_ledger_bind_the_entire_manifest_even_after_local_rehash(planned_inputs):
    plan = controlled_study.create_study_plan(planned_inputs, provider="groq")
    path = planned_inputs / "experiments" / plan["study_id"] / "manifest.json"
    changed = {key: value for key, value in plan.items() if key != "manifest_sha256"}
    changed["shuffle_seed"] += 1
    changed["manifest_sha256"] = canonical_hash(changed)
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="ledger manifest differs"):
        controlled_study.audit_study_plan(planned_inputs, plan["study_id"])


def test_optional_qwen_plan_records_actual_temperature_and_model(planned_inputs, monkeypatch):
    monkeypatch.setenv("LEGACYLIFT_GROQ_MODEL", "qwen/qwen3.8-27b")
    plan = controlled_study.create_study_plan(planned_inputs, provider="groq")
    assert plan["model"] == "qwen/qwen3.8-27b"
    assert plan["temperature"] == 0.7
    assert (
        controlled_study.audit_study_plan(planned_inputs, plan["study_id"])["requests_consumed"]
        == 0
    )


def test_changed_inputs_or_code_cannot_enter_a_controlled_trial(planned_inputs, monkeypatch):
    plan = controlled_study.create_study_plan(planned_inputs, provider="groq")
    (planned_inputs / "evidence/redmine.json").write_text('{"changed":true}')
    with pytest.raises(ValueError, match="code or inputs changed"):
        controlled_study.audit_study_plan(planned_inputs, plan["study_id"])
    cell = plan["cells"][0]
    with pytest.raises(ValueError, match="code or inputs changed"):
        CallLedger(planned_inputs).validate_existing(
            cell["run_id"], controlled_study._binding(plan, cell), seeded=False
        )
    monkeypatch.setattr(call_ledger, "code_hashes", lambda: {"changed": "b" * 64})
    with pytest.raises(ValueError, match="provider/model/code"):
        CallLedger(planned_inputs).reserve(
            plan["cells"][0]["run_id"], 0, "groq", plan["model"], "c" * 64
        )


def test_study_cannot_be_planned_from_changed_or_unsealed_guidance(planned_inputs):
    path = planned_inputs / "study/guidance.json"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="input checksum differs"):
        controlled_study.create_study_plan(planned_inputs, provider="groq")
    (planned_inputs / "study/integrity.json").unlink()
    with pytest.raises(ValueError, match="unsealed"):
        controlled_study.create_study_plan(planned_inputs, provider="groq")
