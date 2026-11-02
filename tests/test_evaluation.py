from __future__ import annotations

import json
from pathlib import Path

import pytest

from legacylift.evaluation import (
    GUIDANCE_SCENARIO_IDS,
    HELD_OUT_SCENARIO_IDS,
    run_evaluation,
    split_scenarios,
    write_evaluation_artifacts,
)
from legacylift.runtime_capture.scenarios import DEFAULT_SCENARIOS


def test_scenario_split_is_complete_and_disjoint():
    guidance, held_out = split_scenarios(DEFAULT_SCENARIOS)

    assert tuple(item.scenario_id for item in guidance) == GUIDANCE_SCENARIO_IDS
    assert tuple(item.scenario_id for item in held_out) == HELD_OUT_SCENARIO_IDS
    assert not ({item.scenario_id for item in guidance} & {item.scenario_id for item in held_out})


def test_scenario_split_rejects_unclassified_cases():
    with pytest.raises(ValueError, match="partition is incomplete"):
        split_scenarios(DEFAULT_SCENARIOS[:-1])


def test_evaluation_isolates_guidance_evidence_and_reports_baseline_honestly():
    guidance_trace, report, record = run_evaluation()

    assert {item["scenario_id"] for item in guidance_trace["scenarios"]} == set(
        GUIDANCE_SCENARIO_IDS
    )
    assert {item.workflow_id for item in record.contracts} == set(GUIDANCE_SCENARIO_IDS)
    assert report["baseline_result"]["scope"] == "held-out scenarios only"
    assert report["baseline_result"]["scenario_match_rate"] == 1.0
    assert report["baseline_result"]["step_match_rate"] == 1.0
    assert report["strategy_comparison"]["status"] == "not_run"
    assert report["strategy_comparison"]["comparative_claims_supported"] is False

    conditions = {item["condition"]: item for item in report["condition_audit"]}
    assert conditions["source_only"]["source_excerpt_char_count"] > 0
    assert conditions["source_only"]["selected_evidence_counts"]["runtime_contracts"] == 0
    assert conditions["runtime_only"]["source_excerpt_char_count"] == 0
    assert conditions["runtime_only"]["runtime_workflows"] == sorted(GUIDANCE_SCENARIO_IDS)
    assert conditions["hybrid"]["runtime_workflows"] == sorted(GUIDANCE_SCENARIO_IDS)
    assert all(not item["held_out_runtime_workflows_in_context"] for item in conditions.values())
    assert all(item["external_provider_calls"] == 0 for item in conditions.values())


def test_checked_in_evaluation_artifacts_match_current_run(tmp_path):
    generated = write_evaluation_artifacts(tmp_path)
    project_root = Path(__file__).parents[1]
    artifact_root = project_root / "artifacts" / "evaluation"

    for name, relative_name in (
        ("guidance_trace", "guidance_trace.json"),
        ("guidance_eer", "guidance_eer.json"),
        ("evaluation_report", "evaluation_report.json"),
    ):
        checked_in = artifact_root / relative_name
        assert generated[name].read_bytes() == checked_in.read_bytes()


def test_evaluation_report_is_stable_across_runs(tmp_path):
    first = write_evaluation_artifacts(tmp_path / "first")
    second = write_evaluation_artifacts(tmp_path / "second")

    assert first["evaluation_report"].read_bytes() == second["evaluation_report"].read_bytes()
    assert json.loads(first["evaluation_report"].read_text(encoding="utf-8"))["baseline_result"][
        "passed"
    ]
