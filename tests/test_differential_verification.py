from __future__ import annotations

import copy
import json
from pathlib import Path

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
