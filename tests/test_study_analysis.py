"""Study reporting must preserve missing observations and actual denominators."""

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def analysis(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / "scripts"))
    return importlib.import_module("analyze_controlled_study")


def observation(run_id, condition, attempts, *, status="compatibility_failed", requests=3):
    return (
        {
            "cell": {
                "run_id": run_id,
                "condition": condition,
                "workflow": "create",
                "replicate": 1,
            },
            "status": status,
            "failure_category": None,
            "workflow_passed": False,
            "guidance_passed": False,
            "held_out_evaluated": False,
            "requests_consumed": requests,
            "requests_without_token_usage": requests - len(attempts),
            "reported_tokens": len(attempts) * 100,
        },
        {"attempts": attempts, "private_source": "DO NOT EXPORT"},
    )


def report(records):
    return {
        "study_id": "synthetic",
        "state": "incomplete",
        "recorded_trials": len(records),
        "planned_trials": 27,
        "condition_counts": {
            name: {"planned": 9} for name in ("source_only", "runtime_only", "hybrid")
        },
        "records": records,
    }


def test_analysis_keeps_pending_and_unreplayed_failures_out_of_score_denominators(analysis):
    failed, result = observation("one", "hybrid", [], status="provider_failed", requests=1)
    measured = analysis.analyze(report([failed]), {"one": result})
    row = measured["trials"][0]
    group = measured["groups"][2]
    assert row["initial_guidance_passed_count"] is None
    assert row["last_replayed_guidance_passed_count"] is None
    assert group["recorded_trials"] == 1 and group["planned_trials"] == 9
    assert group["unknown_usage_requests"] == 1
    assert group["provider_latency_seconds"]["median"] is None
    assert group["nominal_wilson_95_percent"][1] > 0.79
    assert measured["groups"][0]["nominal_wilson_95_percent"] is None
    assert "DO NOT EXPORT" not in str(measured)


def test_analysis_pairs_only_initial_and_later_real_replays_and_keeps_regressions(analysis):
    attempts = [
        {
            "attempt": 0,
            "scenario_count": 6,
            "passed_count": 5,
            "provenance": {"latency_seconds": 1.2},
        },
        {
            "attempt": 1,
            "scenario_count": 6,
            "passed_count": 3,
            "provenance": {"latency_seconds": 2.4},
        },
        {"attempt": 2, "scenario_count": 0, "passed_count": 0},
    ]
    record, result = observation("one", "source_only", attempts, status="static_review_blocked")
    measured = analysis.analyze(report([record]), {"one": result})
    group = measured["groups"][0]
    assert group["paired_repair_trials"] == group["paired_repair_regressed_trials"] == 1
    assert group["paired_repair_improved_trials"] == group["guidance_passing_trials"] == 0
    assert measured["trials"][0]["last_replayed_guidance_passed_count"] == 3
    assert group["provider_latency_seconds"]["observations"] == 2
    assert group["provider_latency_seconds"]["median"] == 1.8
    record, result = observation("two", "hybrid", attempts[1:])
    assert (
        analysis.analyze(report([record]), {"two": result})["groups"][2]["paired_repair_trials"]
        == 0
    )


def test_export_rejects_changed_result_after_audit(analysis, monkeypatch, tmp_path):
    record, _ = observation("one", "hybrid", [])
    record["artifacts"] = {"result.json": "stale-hash"}
    monkeypatch.setattr(analysis, "study_report", lambda *args: report([record]))
    run = tmp_path / "runs" / "one"
    run.mkdir(parents=True)
    (run / "result.json").write_text('{"attempts": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="changed after"):
        analysis.export_analysis(tmp_path, "synthetic", tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_live_runner_rejection_is_propagated_without_export(analysis, monkeypatch, tmp_path):
    def locked(*args):
        raise RuntimeError("another runner is executing this study")

    monkeypatch.setattr(analysis, "study_report", locked)
    with pytest.raises(RuntimeError, match="another runner"):
        analysis.export_analysis(tmp_path, "synthetic", tmp_path / "output")
    assert not (tmp_path / "output").exists()


@pytest.mark.parametrize("successes,total", [(-1, 2), (3, 2), (True, 2)])
def test_invalid_interval_counts_are_rejected(analysis, successes, total):
    with pytest.raises(ValueError):
        analysis.wilson_interval(successes, total)
