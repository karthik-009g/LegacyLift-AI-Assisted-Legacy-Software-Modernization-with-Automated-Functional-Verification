"""Guidance read isolation, immutable seals and independent replay integrity."""

import copy
import json
from pathlib import Path

import pytest

from legacylift.modernization import frozen_study, study
from legacylift.modernization.contracts import canonical_hash


@pytest.fixture
def frozen(frozen_reference_inputs):
    return frozen_reference_inputs


def test_sealing_is_idempotent_preserves_inputs_and_rejects_rewritten_expectations(frozen):
    directory = frozen / "study"
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    seal = frozen_study.seal_study(frozen)
    assert frozen_study.seal_study(frozen) == seal
    assert all((directory / name).read_bytes() == raw for name, raw in before.items())

    # Even internally consistent replacement observations cannot overwrite the prior seal.
    oracle = json.loads((directory / "oracle.json").read_text())
    oracle["scenarios"][0]["steps"][0]["response"]["status"] = 201
    oracle["oracle_sha256"] = canonical_hash(oracle["scenarios"])
    (directory / "oracle.json").write_text(json.dumps(oracle))
    (directory / "guidance.json").write_text(
        json.dumps(
            {**oracle, "scenarios": [c for c in oracle["scenarios"] if c["split"] == "guidance"]}
        )
    )
    with pytest.raises(ValueError, match="checksum differs|immutable"):
        frozen_study.seal_study(frozen)


def test_guidance_replay_never_opens_combined_oracle(frozen, monkeypatch):
    seal = frozen_study.seal_study(frozen)
    original = Path.open

    def no_hidden_reads(path, *args, **kwargs):
        if path.name in {"oracle.json", "held-out.json", ".env"}:
            pytest.fail("guidance replay opened held-out observations or credentials")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_hidden_reads)

    class Target:
        def __init__(self, source, database, actors):
            assert source == "candidate source"
            assert database == b"synthetic database"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def describe(self):
            return {"isolated_test_double": True}

        def diagnostics(self):
            return ""

    monkeypatch.setattr(study, "PythonTarget", Target)
    monkeypatch.setattr(study, "capture", lambda target, cases, checkpoint: copy.deepcopy(cases))
    report = study.evaluate_source("candidate source", frozen, workflow="read")
    assert report["status"] == "passed"
    assert report["scenario_count"] == report["passed_count"] == 6
    assert all(row["split"] == "guidance" for row in report["results"])
    assert report["study_seal_sha256"] == seal["seal_sha256"]


@pytest.mark.parametrize("name", ["guidance.json", "fixture.sqlite3", "actors.private.json"])
def test_changed_guidance_or_fixture_fails_before_candidate_execution(frozen, monkeypatch, name):
    frozen_study.seal_study(frozen)
    path = frozen / "study" / name
    path.write_bytes(path.read_bytes() + b" ")
    monkeypatch.setattr(
        study, "PythonTarget", lambda *args: pytest.fail("tampered study executed a candidate")
    )
    with pytest.raises(ValueError, match="input checksum differs"):
        study.evaluate_source("candidate source", frozen)


def test_unsealed_and_rehashed_invalid_scenario_sets_are_rejected(frozen):
    with pytest.raises(ValueError, match="unsealed"):
        study.evaluate_source("candidate source", frozen)
    path = frozen / "study/oracle.json"
    oracle = json.loads(path.read_text())
    oracle["scenarios"][0]["requests"][0]["path"] = "/different"
    oracle["oracle_sha256"] = canonical_hash(oracle["scenarios"])
    path.write_text(json.dumps(oracle))
    with pytest.raises(ValueError, match="identity or requests"):
        frozen_study.seal_study(frozen)


def test_held_out_artifact_is_separately_checked_and_not_returned_as_guidance(frozen):
    frozen_study.seal_study(frozen)
    guidance, _ = frozen_study.evaluation_artifact(frozen, "guidance")
    assert len(guidance["scenarios"]) == 18
    path = frozen / "study/oracle.json"
    oracle = json.loads(path.read_text())
    oracle["scenarios"][-1]["steps"][0]["response"]["status"] = 201
    path.write_text(json.dumps(oracle))
    # Guidance is separately sealed and still usable without reading the changed oracle.
    frozen_study.evaluation_artifact(frozen, "guidance")
    with pytest.raises(ValueError, match="oracle content checksum"):
        frozen_study.evaluation_artifact(frozen, "held_out")


def test_changed_guidance_between_preflight_and_load_is_rejected(frozen, monkeypatch):
    frozen_study.seal_study(frozen)
    original = frozen_study._read

    def change_before_load(workspace, name):
        if name == "guidance.json":
            path = workspace / "study" / name
            artifact = json.loads(path.read_bytes())
            artifact["scenarios"][0]["steps"][0]["response"]["status"] = 201
            path.write_text(json.dumps(artifact))
        return original(workspace, name)

    monkeypatch.setattr(frozen_study, "_read", change_before_load)
    with pytest.raises(ValueError, match="input checksum differs"):
        frozen_study.evaluation_artifact(frozen, "guidance")


@pytest.mark.parametrize("name", ["fixture.sqlite3", "actors.private.json"])
def test_changed_execution_input_after_preflight_cannot_reach_runtime(frozen, monkeypatch, name):
    frozen_study.seal_study(frozen)
    original = study.evaluation_artifact

    def change_after_preflight(workspace, split):
        artifact, seal = original(workspace, split)
        path = workspace / "study" / name
        path.write_bytes(path.read_bytes() + b" ")
        return artifact, seal

    monkeypatch.setattr(study, "evaluation_artifact", change_after_preflight)
    monkeypatch.setattr(
        study, "PythonTarget", lambda *args: pytest.fail("changed execution input reached runtime")
    )
    with pytest.raises(ValueError, match="input checksum differs"):
        study.evaluate_source("candidate source", frozen)
