from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from legacylift.evidence.builder import build_eer
from legacylift.evidence.schema import EngineeringEvidenceRecord
from legacylift.evidence.storage import load_eer, write_eer, write_eer_schema
from legacylift.runtime_capture.runner import capture_scenarios
from legacylift.static_analysis import analyze_paths


def build_current_record():
    project_root = Path(__file__).parents[1]
    static_report = analyze_paths(
        [project_root / "src" / "legacylift" / "legacy_app"],
        root=project_root,
    )
    return build_eer(static_report, capture_scenarios())


def test_eer_separates_observations_inferences_unknowns_and_contracts():
    record = build_current_record()

    assert record.schema_version == "1.0.0"
    assert record.observed_facts
    assert record.inferences
    assert record.unknowns
    assert record.contracts
    assert len(record.validation_cases) == len(record.contracts)
    assert any(item.kind == "source_ast" for item in record.provenance)
    assert any(item.kind == "runtime_trace" for item in record.provenance)
    assert all(
        set(item.provenance_ids) <= {p.provenance_id for p in record.provenance}
        for item in record.observed_facts + record.inferences + record.unknowns + record.contracts
    )


def test_eer_round_trip_and_json_schema_validate(tmp_path):
    record = build_current_record()
    path = write_eer(record, tmp_path / "record.json")

    loaded = load_eer(path)
    schema = EngineeringEvidenceRecord.model_json_schema()

    assert loaded == record
    assert schema["properties"]["schema_version"]["const"] == "1.0.0"
    assert "observed_facts" in schema["properties"]


def test_checked_in_eer_and_schema_match_current_evidence(tmp_path):
    project_root = Path(__file__).parents[1]
    generated_eer = write_eer(build_current_record(), tmp_path / "current-eer.json")
    generated_schema = write_eer_schema(tmp_path / "current-schema.json")

    assert (
        generated_eer.read_bytes()
        == (project_root / "artifacts" / "evidence" / "ticket_workflows.eer.json").read_bytes()
    )
    assert (
        generated_schema.read_bytes()
        == (
            project_root / "artifacts" / "schemas" / "engineering_evidence_record.schema.json"
        ).read_bytes()
    )


def test_eer_rejects_missing_provenance_and_unknown_fields():
    record = build_current_record().model_dump(mode="json")
    record["observed_facts"][0]["provenance_ids"] = ["missing-source"]

    with pytest.raises(ValidationError, match="unknown provenance references"):
        EngineeringEvidenceRecord.model_validate(record)

    record = build_current_record().model_dump(mode="json")
    record["unreviewed_claim"] = "must not be silently accepted"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EngineeringEvidenceRecord.model_validate(record)
