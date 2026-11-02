from __future__ import annotations

import json
from pathlib import Path

from legacylift.runtime_capture.runner import capture_scenarios, write_trace_bundle


def test_runtime_capture_records_responses_sessions_cookies_and_database_deltas():
    bundle = capture_scenarios()

    assert bundle["trace_schema_version"] == "1.0"
    scenarios = {scenario["scenario_id"]: scenario for scenario in bundle["scenarios"]}
    create_steps = scenarios["create_ticket"]["steps"]
    assert create_steps[0]["session_before"] == {"user_id": None}
    assert create_steps[0]["session_after"] == {"user_id": "alice"}
    assert create_steps[0]["response"]["cookies"][0] == {
        "name": "session",
        "value_redacted": True,
        "http_only": True,
        "secure": False,
        "same_site": None,
        "path": "/",
    }
    assert create_steps[1]["response"]["status"] == 201
    assert create_steps[1]["database_delta"]["added"][0]["subject"] == "Capture scenario"
    assert "set-cookie" not in {name.lower() for name in create_steps[0]["response"]["headers"]}
    assert all(
        cookie["value_redacted"]
        for scenario in bundle["scenarios"]
        for step in scenario["steps"]
        for cookie in step["response"]["cookies"]
    )


def test_runtime_capture_observes_ownership_and_stateful_transitions():
    scenarios = {scenario["scenario_id"]: scenario for scenario in capture_scenarios()["scenarios"]}

    other_owner = scenarios["hide_other_users_ticket"]["steps"][-1]
    assert other_owner["response"]["status"] == 404
    assert other_owner["database_delta"] == {"added": [], "updated": [], "removed": []}

    transitions = scenarios["valid_status_transitions"]["steps"]
    assert [step["response"]["json"]["status"] for step in transitions[1:]] == [
        "in_progress",
        "closed",
    ]
    assert transitions[-1]["database_delta"]["updated"][0]["after"]["status"] == "closed"


def test_trace_bundle_is_byte_for_byte_deterministic(tmp_path):
    first = write_trace_bundle(tmp_path / "first.json")
    second = write_trace_bundle(tmp_path / "second.json")

    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text(encoding="utf-8"))["scenarios"]


def test_checked_in_trace_matches_current_capture(tmp_path):
    generated = write_trace_bundle(tmp_path / "current.json")
    checked_in = Path(__file__).parents[1] / "artifacts" / "traces" / "ticket_workflows.json"

    assert generated.read_bytes() == checked_in.read_bytes()
