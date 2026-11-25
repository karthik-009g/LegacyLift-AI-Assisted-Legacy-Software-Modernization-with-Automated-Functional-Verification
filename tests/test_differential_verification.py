from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi import FastAPI

from legacylift.runtime_capture.scenarios import DEFAULT_SCENARIOS
from legacylift.verification.runner import (
    compare_observations,
    compare_scenarios,
    sample_mismatch_report,
    write_differential_report,
    write_sample_mismatch_report,
)


def test_default_scenarios_match_responses_sessions_and_database_state():
    report = compare_scenarios()

    assert report["summary"] == {
        "passed": True,
        "scenario_count": 6,
        "step_count": 13,
        "passed_step_count": 13,
        "failed_step_count": 0,
    }
    assert all(scenario["passed"] for scenario in report["scenarios"])


def test_mismatch_report_names_the_differing_field():
    report = compare_scenarios()
    legacy = report["scenarios"][0]["steps"][0]["legacy"]
    reconstructed = copy.deepcopy(legacy)
    reconstructed["response"]["status"] = 503

    assert compare_observations(legacy, reconstructed) == [
        {
            "field": "response.status",
            "legacy": 200,
            "reconstructed": 503,
        }
    ]


@pytest.mark.parametrize("changed_id", [True, 1.0])
def test_comparison_preserves_response_json_types(changed_id):
    report = compare_scenarios()
    legacy = copy.deepcopy(report["scenarios"][0]["steps"][0]["legacy"])
    legacy["response"]["json"] = {"tickets": [{"id": 1}]}
    reconstructed = copy.deepcopy(legacy)
    reconstructed["response"]["json"]["tickets"][0]["id"] = changed_id

    mismatches = compare_observations(legacy, reconstructed)

    assert [item["field"] for item in mismatches] == ["response.json"]
    assert type(mismatches[0]["legacy"]["tickets"][0]["id"]) is int
    assert type(mismatches[0]["reconstructed"]["tickets"][0]["id"]) is type(changed_id)


def test_candidate_request_failure_and_missing_observer_are_recorded_without_aborting():
    def faulty_app(_config):
        app = FastAPI()

        @app.post("/session")
        def fail_session():
            raise RuntimeError("synthetic candidate request failure")

        return app

    report = compare_scenarios((DEFAULT_SCENARIOS[0],), reconstructed_app_factory=faulty_app)

    first, second = report["scenarios"][0]["steps"]
    assert report["summary"]["step_count"] == 2
    assert report["summary"]["passed"] is False
    assert first["reconstructed"]["response"]["status"] == 500
    assert first["reconstructed"]["session_before"] is None
    assert first["reconstructed"]["session_after"] is None
    assert "received 0" in first["reconstructed"]["session_observation_error"]
    assert {entry["field"] for entry in first["mismatches"]} >= {
        "response.status",
        "session_before",
        "session_after",
    }
    assert second["reconstructed"]["response"]["status"] == 404


def test_differential_report_is_byte_for_byte_deterministic(tmp_path):
    first = write_differential_report(tmp_path / "first.json")
    second = write_differential_report(tmp_path / "second.json")

    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text(encoding="utf-8"))["summary"]["passed"]


def test_checked_in_differential_report_matches_current_comparison(tmp_path):
    generated = write_differential_report(tmp_path / "current.json")
    checked_in = (
        Path(__file__).parents[1] / "artifacts" / "verification" / "differential_report.json"
    )

    assert generated.read_bytes() == checked_in.read_bytes()


def test_sample_mismatch_report_is_labeled_and_reproducible(tmp_path):
    report = sample_mismatch_report()
    generated = write_sample_mismatch_report(tmp_path / "sample.json")
    checked_in = Path(__file__).parents[1] / "artifacts" / "verification" / "sample_mismatch.json"

    assert report["report_kind"] == "synthetic_mutation_example"
    assert report["passed"] is False
    assert report["mismatches"] == [
        {"field": "response.status", "legacy": 200, "reconstructed": 418}
    ]
    assert generated.read_bytes() == checked_in.read_bytes()
