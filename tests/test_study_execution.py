"""Exercise real study state/ledger/locks with simulated migrations, never cloud calls."""

import json
import subprocess
import sys

import pytest

from legacylift.modernization import controlled_study, study_execution
from legacylift.modernization.call_ledger import CallLedger
from legacylift.modernization.contracts import canonical_hash
from legacylift.modernization.frozen_study import seal_study
from legacylift.modernization.study import write_json


@pytest.fixture
def planned(frozen_reference_inputs, monkeypatch):
    home = frozen_reference_inputs
    (home / "evidence").mkdir()
    (home / "evidence/redmine.json").write_text("{}")
    (home / "evidence/runtime_routes.json").write_text("{}")
    seal_study(home)
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
    return home, controlled_study.create_study_plan(home, provider="groq", seed=7)


def fake_migration(home, plan, calls, *, status="compatibility_failed"):
    """Persist the same durable boundaries the real pipeline promises to the runner."""
    cells = {cell["run_id"]: cell for cell in plan["cells"]}

    def migrate(workspace, **kwargs):
        calls.append(kwargs)
        cell = cells[kwargs["run_id"]]
        assert workspace == home
        assert kwargs["workflow"] == cell["workflow"]
        assert kwargs["condition"] == cell["condition"]
        assert kwargs["provider"] == plan["provider"]
        assert kwargs["max_repairs"] == 2
        assert not kwargs.get("retry_failed_call") and not kwargs.get("seed_run_id")
        ledger = CallLedger(home)
        request = ledger.reserve(cell["run_id"], 0, plan["provider"], plan["model"], "a" * 64)
        ledger.finish(
            [(request, plan["provider"])], [{"provider": plan["provider"], "status": "generated"}]
        )
        directory = home / "runs" / cell["run_id"]
        directory.mkdir(parents=True, exist_ok=True)
        source = "# Synthetic runner test; never a migration result\napp = None\n"
        (directory / "app.py").write_text(source)
        result = {
            "run_id": cell["run_id"],
            **controlled_study._binding(plan, cell),
            "status": status,
            "held_out_evaluated": False,
            "attempts": [
                {
                    "attempt": 0,
                    "source_sha256": canonical_hash(source),
                    "passed_count": 6 if status == "passed" else 2,
                    "scenario_count": 6,
                    "provenance": {
                        "provider": plan["provider"],
                        "model": plan["model"],
                        "usage": {"total_tokens": 100},
                    },
                }
            ]
            if status not in {"provider_failed", "provider_paused"}
            else [],
        }
        write_json(directory / "result.json", result)
        return result

    return migrate


def fake_finalization(home, calls, *, status="passed"):
    def finalize(workspace, run_id, checkpoint):
        calls.append(run_id)
        directory = home / "runs" / run_id
        result = json.loads((directory / "result.json").read_text())
        report = {
            "source_sha256": result["attempts"][-1]["source_sha256"],
            "status": status,
            "passed_count": 4 if status == "passed" else 2,
            "scenario_count": 4,
            "repair_feedback_allowed": False,
        }
        write_json(directory / "held-out.json", report)
        result.update(
            {
                "held_out_evaluated": True,
                "held_out_status": status,
                "held_out_passed_count": report["passed_count"],
                "held_out_scenario_count": 4,
                "held_out_report_sha256": canonical_hash(report),
            }
        )
        write_json(directory / "result.json", result)
        return report

    return finalize


def test_fixed_order_bounded_batches_and_completed_resume_never_repeat_requests(
    planned, monkeypatch
):
    home, plan = planned
    calls = []
    monkeypatch.setattr(study_execution, "migrate", fake_migration(home, plan, calls))
    monkeypatch.setattr(
        study_execution, "finalize", lambda *args: pytest.fail("failed guidance finalized")
    )
    first = study_execution.run_study(home, plan["study_id"])
    assert first["recorded_trials"] == first["requests_consumed"] == 1
    assert first["state"] == "incomplete"
    complete = study_execution.run_study(home, plan["study_id"], max_trials=27)
    assert complete["state"] == "completed"
    assert complete["recorded_trials"] == complete["requests_consumed"] == 27
    assert complete["workflow_passing_trials"] == 0
    assert complete["outcome_counts"] == {"compatibility_failed": 27}
    assert all(
        group["planned"] == group["recorded"] == 9
        for group in complete["condition_counts"].values()
    )
    assert [call["run_id"] for call in calls] == [cell["run_id"] for cell in plan["cells"]]
    study_execution.run_study(home, plan["study_id"], max_trials=27)
    assert len(calls) == 27
    report = study_execution.study_report(home, plan["study_id"])
    assert report["reported_tokens"] == 2700
    assert report["security_verdict"] == "not_assessed"
    assert "private-actor-marker" not in json.dumps(report)


def test_provider_pause_is_recorded_and_stops_batch_without_resending_it(planned, monkeypatch):
    home, plan = planned
    calls = []
    monkeypatch.setattr(
        study_execution, "migrate", fake_migration(home, plan, calls, status="provider_paused")
    )
    paused = study_execution.run_study(home, plan["study_id"], max_trials=27)
    assert paused["recorded_trials"] == paused["requests_consumed"] == 1
    assert paused["stop_reason"] == "provider_paused"
    assert paused["requests_without_token_usage"] == 1
    assert paused["reported_tokens"] == 0
    # A new explicit invocation advances to the next prespecified cell, never retries the old one.
    study_execution.run_study(home, plan["study_id"])
    assert [call["run_id"] for call in calls] == [cell["run_id"] for cell in plan["cells"][:2]]


@pytest.mark.parametrize("held_out_status", ["passed", "compatibility_failed"])
def test_guidance_gate_finalizes_once_and_keeps_held_out_failure_final(
    planned, monkeypatch, held_out_status
):
    home, plan = planned
    calls, finalized = [], []
    monkeypatch.setattr(
        study_execution, "migrate", fake_migration(home, plan, calls, status="passed")
    )
    monkeypatch.setattr(
        study_execution, "finalize", fake_finalization(home, finalized, status=held_out_status)
    )
    report = study_execution.run_study(home, plan["study_id"])
    assert len(calls) == len(finalized) == 1
    assert report["held_out_evaluated_trials"] == 1
    assert report["workflow_passing_trials"] == (1 if held_out_status == "passed" else 0)
    assert report["records"][0]["security_verdict"] == "not_assessed"
    study_execution.study_report(home, plan["study_id"])
    assert len(calls) == len(finalized) == 1


def test_crash_after_durable_result_resumes_without_another_provider_request(planned, monkeypatch):
    home, plan = planned
    calls = []
    perform = fake_migration(home, plan, calls)

    def crash_after_result(*args, **kwargs):
        perform(*args, **kwargs)
        raise RuntimeError("simulated controller interruption")

    monkeypatch.setattr(study_execution, "migrate", crash_after_result)
    interrupted = study_execution.run_study(home, plan["study_id"])
    assert interrupted["stop_reason"] == "controller_interrupted"
    assert interrupted["in_progress"] == plan["cells"][0]["run_id"]
    assert interrupted["requests_consumed"] == interrupted["requests_without_token_usage"] == 1
    assert interrupted["recorded_trials"] == 0
    monkeypatch.setattr(
        study_execution, "migrate", lambda *a, **kw: pytest.fail("durable result resent")
    )
    resumed = study_execution.run_study(home, plan["study_id"])
    assert resumed["recorded_trials"] == resumed["requests_consumed"] == 1
    assert resumed["in_progress"] is None
    assert len(calls) == 1


def test_changed_recorded_artifacts_or_trial_identity_fail_closed(planned, monkeypatch):
    home, plan = planned
    calls = []
    monkeypatch.setattr(study_execution, "migrate", fake_migration(home, plan, calls))
    study_execution.run_study(home, plan["study_id"])
    result_path = home / "runs" / plan["cells"][0]["run_id"] / "result.json"
    result = json.loads(result_path.read_text())
    result["status"] = "passed"
    write_json(result_path, result)
    with pytest.raises(ValueError, match="artifacts changed|guidance pass"):
        study_execution.run_study(home, plan["study_id"])
    assert len(calls) == 1


def test_same_study_cannot_have_two_active_runners(planned, monkeypatch):
    home, plan = planned
    monkeypatch.setattr(
        study_execution, "migrate", lambda *a, **kw: pytest.fail("concurrent execution")
    )
    path = home / "experiments" / plan["study_id"] / "runner.lock"
    with study_execution._exclusive_runner(path):
        with pytest.raises(RuntimeError, match="another runner"):
            study_execution.run_study(home, plan["study_id"])


def test_os_lock_is_released_after_actual_child_process_exit(planned):
    home, plan = planned
    path = home / "experiments" / plan["study_id"] / "runner.lock"
    script = (
        "import os,sys; from pathlib import Path; "
        "from legacylift.modernization.study_execution import _exclusive_runner; "
        "lock=_exclusive_runner(Path(sys.argv[1])); lock.__enter__(); os._exit(0)"
    )
    process = subprocess.run(
        [sys.executable, "-c", script, str(path)],
        capture_output=True,
        timeout=20,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert process.returncode == 0
    with study_execution._exclusive_runner(path):
        assert path.is_file()


def test_wrong_durable_trial_identity_never_opens_held_out_verification(planned, monkeypatch):
    home, plan = planned
    calls = []
    perform = fake_migration(home, plan, calls, status="passed")

    def wrong_identity(*args, **kwargs):
        result = perform(*args, **kwargs)
        result["condition"] = "different_condition"
        write_json(home / "runs" / kwargs["run_id"] / "result.json", result)
        return result

    monkeypatch.setattr(study_execution, "migrate", wrong_identity)
    monkeypatch.setattr(
        study_execution, "finalize", lambda *args: pytest.fail("wrong trial finalized")
    )
    report = study_execution.run_study(home, plan["study_id"])
    assert report["stop_reason"] == "controller_interrupted"
    assert report["recorded_trials"] == 0


@pytest.mark.parametrize("limit", [0, 28, True, -1])
def test_invalid_batch_limits_are_rejected_before_execution(planned, limit):
    home, plan = planned
    with pytest.raises(ValueError, match="max_trials"):
        study_execution.run_study(home, plan["study_id"], max_trials=limit)


def test_report_cli_does_not_load_provider_credentials(planned, monkeypatch, capsys):
    from legacylift import cli
    from legacylift.workbench.cli import main

    home, plan = planned
    loads = []
    monkeypatch.setattr(cli, "_load_project_env", lambda path, **kw: loads.append(kw))
    assert main(["--home", str(home), "study-report", plan["study_id"]]) == 0
    assert loads == [{"include_provider_keys": False}]
    output = json.loads(capsys.readouterr().out)
    assert output["recorded_trials"] == output["requests_consumed"] == 0


def test_rehashed_success_label_cannot_override_actual_trial_results(planned, monkeypatch):
    home, plan = planned
    monkeypatch.setattr(study_execution, "migrate", fake_migration(home, plan, []))
    study_execution.run_study(home, plan["study_id"])
    path = home / "experiments" / plan["study_id"] / "execution.json"
    state = json.loads(path.read_text())
    record = state["records"][0]
    record["workflow_passed"] = True
    record["record_sha256"] = canonical_hash(
        {key: value for key, value in record.items() if key != "record_sha256"}
    )
    write_json(path, state)
    with pytest.raises(ValueError, match="content or artifacts changed"):
        study_execution.study_report(home, plan["study_id"])


def test_inconsistent_held_out_pass_cannot_be_recorded_as_workflow_success(planned, monkeypatch):
    home, plan = planned
    monkeypatch.setattr(study_execution, "migrate", fake_migration(home, plan, [], status="passed"))
    finalize = fake_finalization(home, [])

    def inconsistent_finalization(workspace, run_id, checkpoint):
        finalize(workspace, run_id, checkpoint)
        directory = home / "runs" / run_id
        report = json.loads((directory / "held-out.json").read_text())
        report["passed_count"] = 2
        write_json(directory / "held-out.json", report)
        result = json.loads((directory / "result.json").read_text())
        result["held_out_passed_count"] = 2
        result["held_out_report_sha256"] = canonical_hash(report)
        write_json(directory / "result.json", result)

    monkeypatch.setattr(study_execution, "finalize", inconsistent_finalization)
    report = study_execution.run_study(home, plan["study_id"])
    assert report["stop_reason"] == "controller_interrupted"
    assert report["recorded_trials"] == report["workflow_passing_trials"] == 0
