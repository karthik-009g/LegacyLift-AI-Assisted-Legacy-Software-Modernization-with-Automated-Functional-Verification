"""Workbench controls must reach the worker and preserve saved run/budget settings."""

import json

import pytest
from fastapi.testclient import TestClient

from legacylift.modernization.call_ledger import CallLedger
from legacylift.workbench import jobs
from legacylift.workbench.api import create_app

CLIENT = {"X-LegacyLift-Client": "workbench"}


@pytest.fixture
def prepared_home(tmp_path, monkeypatch):
    monkeypatch.delenv("LEGACYLIFT_DATABASE_URL", raising=False)
    monkeypatch.delenv("LEGACYLIFT_REDIS_URL", raising=False)
    (tmp_path / "study").mkdir()
    (tmp_path / "study/oracle.json").write_text("{}")
    return tmp_path


def test_staged_settings_survive_api_queue_and_worker_dispatch(prepared_home, monkeypatch):
    captured = {}

    def migrate(home, **kwargs):
        captured.update(kwargs)
        assert home == prepared_home
        return {"status": "provider_paused", "run_id": kwargs["run_id"]}

    monkeypatch.setattr(jobs, "migrate", migrate)
    with TestClient(create_app(prepared_home, start_jobs=False)) as client:
        response = client.post(
            "/api/jobs",
            headers=CLIENT,
            json={
                "kind": "migrate",
                "provider": "groq",
                "staged_read": True,
                "groq_reasoning_effort": "low",
            },
        )
        assert response.status_code == 202
        jobs.execute_job(str(prepared_home), response.json()["id"])
        assert captured["staged_read"] is True
        assert captured["groq_reasoning_effort"] == "low"
        assert captured["provider"] == "groq"
        assert client.get(f"/api/jobs/{response.json()['id']}").json()["state"] == "quota_paused"


@pytest.mark.parametrize(
    "settings",
    [
        {"staged_read": True, "provider": "auto"},
        {"staged_read": True, "provider": "openrouter"},
        {"staged_read": True, "provider": "groq", "workflow": "create"},
        {"staged_read": True, "provider": "groq", "condition": "runtime_only"},
        {"groq_reasoning_effort": "low", "provider": "groq"},
        {"staged_read": True, "groq_reasoning_effort": "low", "provider": "gemini"},
        {"kind": "prepare", "staged_read": True},
    ],
)
def test_invalid_generation_modes_are_rejected_before_queueing(prepared_home, settings):
    with TestClient(create_app(prepared_home, start_jobs=False)) as client:
        response = client.post("/api/jobs", headers=CLIENT, json={"kind": "migrate", **settings})
        assert response.status_code == 422
        assert client.get("/api/jobs").json() == []


def saved_staged_run(home):
    directory = home / "runs/savedstage"
    directory.mkdir(parents=True)
    (directory / "context.json").write_text(
        json.dumps(
            {
                "read_generation_strategy": "staged-bodies-v3",
                "groq_reasoning_effort": "low",
                "unrelated_private_metadata": "not for the UI",
            }
        )
    )
    (directory / "result.json").write_text(
        json.dumps(
            {
                "run_id": directory.name,
                "status": "provider_paused",
                "workflow": "read",
                "condition": "hybrid",
                "provider_policy": "groq",
                "max_repairs": 2,
                "attempts": [],
            }
        )
    )
    return directory


def test_resume_infers_saved_settings_and_rejects_changed_mode_or_reasoning(prepared_home):
    directory = saved_staged_run(prepared_home)
    payload = {"kind": "migrate", "run_id": directory.name, "retry_failed_call": True}
    with TestClient(create_app(prepared_home, start_jobs=False)) as client:
        detail = client.get(f"/api/runs/{directory.name}").json()
        assert detail["generation_settings"] == {
            "staged_read": True,
            "groq_reasoning_effort": "low",
        }
        assert "not for the UI" not in json.dumps(detail)
        for changed in ({"staged_read": False}, {"groq_reasoning_effort": "high"}):
            assert (
                client.post("/api/jobs", headers=CLIENT, json={**payload, **changed}).status_code
                == 409
            )
        response = client.post("/api/jobs", headers=CLIENT, json=payload)
        assert response.status_code == 202
        parameters = client.get(f"/api/jobs/{response.json()['id']}").json()["parameters"]
        assert parameters["staged_read"] is True and parameters["groq_reasoning_effort"] == "low"


def test_exhausted_saved_run_shows_live_budget_and_cannot_queue_retry(prepared_home):
    directory = saved_staged_run(prepared_home)
    original = (directory / "result.json").read_bytes()
    ledger = CallLedger(prepared_home)
    ledger.register(directory.name, {})
    for _ in range(3):
        ledger.reserve(directory.name, 0, "groq", "fixture-model", "a" * 64)
    with TestClient(create_app(prepared_home, start_jobs=False)) as client:
        detail = client.get(f"/api/runs/{directory.name}").json()
        assert detail["result"]["call_ledger"]["remaining"] == 0
        response = client.post(
            "/api/jobs",
            headers=CLIENT,
            json={
                "kind": "migrate",
                "run_id": directory.name,
                "retry_failed_call": True,
            },
        )
        assert response.status_code == 409 and "exhausted" in response.json()["detail"]
        assert client.get("/api/jobs").json() == []
    assert (directory / "result.json").read_bytes() == original


def test_gemini_staging_needs_no_groq_reasoning_setting(prepared_home):
    with TestClient(create_app(prepared_home, start_jobs=False)) as client:
        response = client.post(
            "/api/jobs",
            headers=CLIENT,
            json={
                "kind": "migrate",
                "staged_read": True,
                "provider": "gemini",
            },
        )
        assert response.status_code == 202
        assert response.json()["parameters"]["staged_read"] is True
        assert "groq_reasoning_effort" not in response.json()["parameters"]
