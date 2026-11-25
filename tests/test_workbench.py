from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from datetime import timedelta
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, update
from sqlalchemy.orm import Session

from legacylift.modernization.contracts import canonical_hash
from legacylift.modernization.security import review_source
from legacylift.workbench.api import create_app
from legacylift.workbench.cli import _worker_type
from legacylift.workbench.jobs import execute_job
from legacylift.workbench.store import Job, Store, utcnow

CLIENT = {"X-LegacyLift-Client": "workbench"}


def test_health_reports_configured_groq_model_without_key_value(tmp_path, monkeypatch):
    monkeypatch.delenv("LEGACYLIFT_DATABASE_URL", raising=False)
    monkeypatch.setenv("LEGACYLIFT_GROQ_MODEL", "qwen/qwen3.8-27b")
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-private-marker")
    with TestClient(create_app(tmp_path, start_jobs=False)) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["providers"]["groq"] == {"configured": True, "model": "qwen/qwen3.8-27b"}
    assert "synthetic-private-marker" not in response.text


def test_rq_worker_uses_non_forking_implementation_on_windows():
    from rq import SimpleWorker, Worker

    assert _worker_type("nt") is SimpleWorker
    assert _worker_type("posix") is Worker


def test_named_cli_run_can_be_inspected_and_selected_for_resume(tmp_path, monkeypatch):
    from legacylift.workbench.api import StartJob

    monkeypatch.delenv("LEGACYLIFT_DATABASE_URL", raising=False)
    run_id = "namedTrial20261122"
    directory = tmp_path / "runs" / run_id
    directory.mkdir(parents=True)
    result = {"run_id": run_id, "status": "compatibility_failed", "attempts": []}
    (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")
    with TestClient(create_app(tmp_path, start_jobs=False)) as client:
        assert client.get(f"/api/runs/{run_id}").json()["result"] == result
        assert client.get("/api/runs").json() == [result]
    assert StartJob(kind="migrate", run_id=run_id).run_id == run_id
    for unsafe in ["../outside", "a/b", "a" * 65]:
        with pytest.raises(ValueError):
            StartJob(kind="migrate", run_id=unsafe)


def test_job_claim_cancel_and_duplicate_delivery_are_persistent(tmp_path, monkeypatch):
    monkeypatch.delenv("LEGACYLIFT_DATABASE_URL", raising=False)
    store = Store(tmp_path)
    store.initialize()
    job = store.create("prepare", {})
    assert store.claim(job["id"], "worker1")
    assert not store.claim(job["id"], "worker2")
    assert store.checkpoint(job["id"], "worker1", "Observing", 0.3)
    assert not store.checkpoint(job["id"], "worker2", "Should not write", 0.8)
    assert store.cancel(job["id"])["state"] == "cancelling"
    assert not store.checkpoint(job["id"], "worker1", "Stop", 0.4)
    store.finish(job["id"], "worker1", "succeeded", result={"status": "passed"})
    assert Store(tmp_path).get(job["id"])["state"] == "cancelled"
    execute_job(str(tmp_path), job["id"])  # Must not rerun a terminal job.
    assert store.get(job["id"])["state"] == "cancelled"
    store.engine.dispose()


def test_restart_recovery_preserves_live_worker_and_marks_only_stale_jobs(tmp_path, monkeypatch):
    monkeypatch.delenv("LEGACYLIFT_DATABASE_URL", raising=False)
    store = Store(tmp_path)
    store.initialize()
    old, fresh = store.create("prepare", {}), store.create("prepare", {})
    store.claim(old["id"], "a")
    store.claim(fresh["id"], "b")
    with Session(store.engine) as session:
        session.execute(
            update(Job).where(Job.id == old["id"]).values(updated_at=utcnow() - timedelta(hours=1))
        )
        session.commit()
    assert store.recover_stale() == 1
    assert store.get(old["id"])["state"] == "interrupted"
    assert store.get(fresh["id"])["state"] == "running"
    store.engine.dispose()


def test_api_restart_recovers_job_left_running_by_a_crashed_worker(tmp_path, monkeypatch):
    monkeypatch.delenv("LEGACYLIFT_DATABASE_URL", raising=False)
    store = Store(tmp_path)
    store.initialize()
    job = store.create("prepare", {})
    store.engine.dispose()

    # Exit without Python cleanup, matching a worker process that disappears mid-job.
    claim_script = (
        "import os, sys\n"
        "from pathlib import Path\n"
        "from legacylift.workbench.store import Store\n"
        "store = Store(Path(sys.argv[1]))\n"
        "store.initialize()\n"
        "if not store.claim(sys.argv[2], 'crashed-worker'):\n"
        "    os._exit(2)\n"
        "os._exit(0)\n"
    )
    child = subprocess.run(
        [sys.executable, "-c", claim_script, str(tmp_path), job["id"]],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert child.returncode == 0, child.stderr

    # Model the lease aging past the startup recovery threshold.
    restarted_store = Store(tmp_path)
    with Session(restarted_store.engine) as session:
        session.execute(
            update(Job)
            .where(Job.id == job["id"])
            .values(updated_at=utcnow() - timedelta(minutes=11))
        )
        session.commit()
    restarted_store.engine.dispose()

    with TestClient(create_app(tmp_path, start_jobs=False)) as client:
        recovered = client.get(f"/api/jobs/{job['id']}").json()
        assert recovered["state"] == "interrupted"
        assert recovered["message"] == "Worker lease expired; start a new job explicitly"

    store = Store(tmp_path)
    assert not store.claim(job["id"], "restart-worker")
    store.engine.dispose()


def test_api_rejects_cross_origin_mutation_and_requires_reference(tmp_path, monkeypatch):
    monkeypatch.delenv("LEGACYLIFT_DATABASE_URL", raising=False)
    with TestClient(create_app(tmp_path, start_jobs=False)) as client:
        assert client.get("/api/health").json()["prepared"] is False
        assert client.post("/api/jobs", json={"kind": "prepare"}).status_code == 403
        assert (
            client.post(
                "/api/jobs",
                headers=CLIENT | {"Origin": "https://evil.example"},
                json={"kind": "prepare"},
            ).status_code
            == 403
        )
        assert client.post("/api/jobs", headers=CLIENT, json={"kind": "migrate"}).status_code == 409
        response = client.post("/api/jobs", headers=CLIENT, json={"kind": "prepare"})
        assert response.status_code == 202
        job_id = response.json()["id"]
        assert (
            client.post(f"/api/jobs/{job_id}/cancel", headers=CLIENT, json={}).json()["state"]
            == "cancelled"
        )


def test_api_queues_explicit_provider_retry_for_the_existing_run(tmp_path, monkeypatch):
    monkeypatch.delenv("LEGACYLIFT_DATABASE_URL", raising=False)
    (tmp_path / "study").mkdir()
    (tmp_path / "study/oracle.json").write_text("{}", encoding="utf-8")
    run_id = "b" * 32
    run_directory = tmp_path / "runs" / run_id
    run_directory.mkdir(parents=True)
    (run_directory / "result.json").write_text(
        json.dumps(
            {
                "status": "provider_paused",
                "workflow": "read",
                "condition": "hybrid",
                "provider_policy": "groq",
                "max_repairs": 2,
            }
        ),
        encoding="utf-8",
    )
    with TestClient(create_app(tmp_path, start_jobs=False)) as client:
        no_run_id = client.post(
            "/api/jobs",
            headers=CLIENT,
            json={"kind": "migrate", "retry_failed_call": True},
        )
        assert no_run_id.status_code == 422
        changed_provider = client.post(
            "/api/jobs",
            headers=CLIENT,
            json={
                "kind": "migrate",
                "run_id": run_id,
                "retry_failed_call": True,
                "provider": "auto",
            },
        )
        assert changed_provider.status_code == 409
        response = client.post(
            "/api/jobs",
            headers=CLIENT,
            json={"kind": "migrate", "run_id": run_id, "retry_failed_call": True},
        )
        assert response.status_code == 202
        job = client.get(f"/api/jobs/{response.json()['id']}").json()
        assert job["parameters"]["run_id"] == run_id
        assert job["parameters"]["retry_failed_call"] is True


def test_api_resumes_only_a_saved_draft_after_local_prompt_rejection(tmp_path, monkeypatch):
    monkeypatch.delenv("LEGACYLIFT_DATABASE_URL", raising=False)
    (tmp_path / "study").mkdir()
    (tmp_path / "study/oracle.json").write_text("{}", encoding="utf-8")
    run_id = "a" * 32
    directory = tmp_path / "runs" / run_id
    directory.mkdir(parents=True)
    (directory / "draft-0.py").write_text("app = None\n", encoding="utf-8")
    (directory / "result.json").write_text(
        json.dumps(
            {
                "status": "provider_failed",
                "workflow": "read",
                "condition": "hybrid",
                "max_repairs": 1,
                "failure": {
                    "category": "prompt_too_large",
                    "attempt": 1,
                    "retryable": False,
                },
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "kind": "migrate",
        "workflow": "read",
        "condition": "hybrid",
        "max_repairs": 1,
        "run_id": run_id,
        "retry_failed_call": True,
    }
    with TestClient(create_app(tmp_path, start_jobs=False)) as client:
        detail = client.get(f"/api/runs/{run_id}").json()
        assert detail["result"]["failure"]["local_rebuild_available"] is True
        response = client.post("/api/jobs", headers=CLIENT, json=payload)
        assert response.status_code == 202
        (directory / "call-1.json").write_text("{}", encoding="utf-8")
        rejected = client.post("/api/jobs", headers=CLIENT, json=payload)
        assert rejected.status_code == 409


def test_worker_maps_migration_run_id_separately_from_job_id(tmp_path, monkeypatch):
    monkeypatch.delenv("LEGACYLIFT_DATABASE_URL", raising=False)
    import legacylift.workbench.jobs as worker

    observed = {}

    def fake_migrate(home, **kwargs):
        observed.update(kwargs)
        return {"status": "provider_paused", "failure": {"category": "quota_exhausted"}}

    monkeypatch.setattr(worker, "migrate", fake_migrate)
    store = Store(tmp_path)
    store.initialize()
    run_id = "d" * 32
    job = store.create("migrate", {"run_id": run_id, "retry_failed_call": True})
    execute_job(str(tmp_path), job["id"])
    saved = store.get(job["id"])
    assert observed["run_id"] == run_id
    assert observed["retry_failed_call"] is True
    assert saved["state"] == "quota_paused"
    store.engine.dispose()


@pytest.mark.parametrize("scaffolded", [False, True])
def test_export_requires_review_of_exact_verified_source(tmp_path, monkeypatch, scaffolded):
    from legacylift.modernization.scaffold import CREATE_SCAFFOLD, source_assembly_metadata

    monkeypatch.delenv("LEGACYLIFT_DATABASE_URL", raising=False)
    run_id = "a" * 32
    directory = tmp_path / "runs" / run_id
    directory.mkdir(parents=True)
    source = "from fastapi import FastAPI\napp = FastAPI()\n"
    assembly = None
    if scaffolded:
        fragment = "def create_issue(api_key, payload, base_url):\n    return None\n"
        source = CREATE_SCAFFOLD + fragment
        assembly = source_assembly_metadata(CREATE_SCAFFOLD, fragment)
    final_report = {
        "status": "passed",
        "source_sha256": canonical_hash(source),
        "passed_count": 4,
        "scenario_count": 4,
    }
    (directory / "app.py").write_text(source)
    result = {"status": "passed", "held_out_report_sha256": canonical_hash(final_report)}
    if scaffolded:
        result["attempts"] = [{"source_assembly": assembly}]
    (directory / "result.json").write_text(json.dumps(result))
    (directory / "held-out.json").write_text(json.dumps(final_report))
    with TestClient(create_app(tmp_path, start_jobs=False)) as client:
        assert client.get(f"/api/runs/{run_id}/export").status_code == 409
        body = {
            "reviewer": "Local reviewer",
            "notes": "Inspected source and limitations",
            "source_sha256": canonical_hash(source),
            "reviewed_source_and_limitations": True,
        }
        assert (
            client.post(f"/api/runs/{run_id}/approve", headers=CLIENT, json=body).status_code == 200
        )
        exported = client.get(f"/api/runs/{run_id}/export")
        assert exported.status_code == 200
        assert exported.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(BytesIO(exported.content)) as archive:
            review = json.loads(archive.read("review.json"))
            assert review["verification_sha256"] == canonical_hash(final_report)
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["source_sha256"] == canonical_hash(source)
            assert manifest["files"] == {
                name: hashlib.sha256(archive.read(name)).hexdigest()
                for name in archive.namelist()
                if name != "manifest.json"
            }
            assert archive.namelist() == sorted(archive.namelist())
            assert {item.date_time for item in archive.infolist()} == {(1980, 1, 1, 0, 0, 0)}
            if scaffolded:
                assert json.loads(archive.read("source-assembly.json")) == assembly
        # The same approved content remains identical across time and JSON serialization.
        (directory / "held-out.json").write_text(
            json.dumps(dict(reversed(list(final_report.items()))), indent=4)
        )
        with monkeypatch.context() as clock_patch:
            clock_patch.setattr(zipfile.time, "localtime", lambda *args: (2035, 7, 8, 9, 10, 12))
            repeated = client.get(f"/api/runs/{run_id}/export")
        assert repeated.content == exported.content
        assert repeated.headers["etag"] == f'"{hashlib.sha256(exported.content).hexdigest()}"'
        if scaffolded:
            tampered = {**assembly, "fragment_sha256": "0" * 64}
            (directory / "result.json").write_text(
                json.dumps({**result, "attempts": [{"source_assembly": tampered}]})
            )
            assert client.get(f"/api/runs/{run_id}/export").status_code == 409
            (directory / "result.json").write_text(json.dumps(result))
        changed_report = {**final_report, "passed_count": 0}
        (directory / "held-out.json").write_text(json.dumps(changed_report))
        assert client.get(f"/api/runs/{run_id}/export").status_code == 409
        assert client.get(f"/api/runs/{run_id}").json()["approval"] is None
        assert (
            client.post(f"/api/runs/{run_id}/approve", headers=CLIENT, json=body).status_code == 409
        )
        (directory / "held-out.json").write_text(json.dumps(final_report))
        (directory / "app.py").write_text(source + "# changed\n")
        assert client.get(f"/api/runs/{run_id}/export").status_code == 409


def test_store_upgrades_existing_approval_table_with_verification_digest(tmp_path):
    store = Store(tmp_path)
    with store.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE approvals ("
            "run_id VARCHAR(32) PRIMARY KEY, source_sha256 VARCHAR(64) NOT NULL, "
            "reviewer VARCHAR(100) NOT NULL, notes TEXT NOT NULL, created_at DATETIME NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO approvals (run_id, source_sha256, reviewer, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                "d" * 32,
                "e" * 64,
                "Previous reviewer",
                "Reviewed before upgrade",
                "2026-11-17 00:00:00",
            ),
        )
    store.initialize()

    columns = {column["name"] for column in inspect(store.engine).get_columns("approvals")}
    assert "verification_sha256" in columns
    assert store.approval("d" * 32)["verification_sha256"] is None


@pytest.mark.parametrize(
    "source",
    ["import subprocess", "eval('1')", "import ctypes", "from os import system\nsystem('x')"],
)
def test_static_policy_blocks_declared_dangerous_capabilities(source):
    result = review_source(source)
    assert result["status"] == "blocked"
    assert result["certified_secure"] is False


@pytest.mark.parametrize("source", ["import yaml", "from dateutil import parser"])
def test_static_policy_blocks_dependencies_outside_the_runtime_allowlist(source):
    result = review_source(source)
    assert result["status"] == "blocked"
    assert result["findings"][0]["rule"] == "unsupported_dependency"


def test_static_policy_allows_standard_library_fastapi_and_sqlalchemy():
    result = review_source(
        "import json, sqlite3\nfrom fastapi import FastAPI\nfrom sqlalchemy import text\n"
        "app = FastAPI()\n"
    )
    assert result["status"] == "static_review_passed"


def test_static_policy_blocks_empty_candidate_source():
    result = review_source(" \n\t\n")
    assert result["status"] == "blocked"
    assert result["findings"] == [{"rule": "empty_source", "line": 1}]


def test_static_policy_requires_module_level_asgi_app():
    result = review_source("from fastapi import FastAPI\n\ndef make_app():\n    return FastAPI()\n")
    assert result["status"] == "blocked"
    assert result["findings"] == [{"rule": "missing_asgi_app", "line": 1}]


@pytest.mark.parametrize("status_code", [401, 403, 404])
def test_static_policy_reports_http_body_compatibility_for_runtime_verification(status_code):
    result = review_source(
        "from fastapi import HTTPException\n"
        "def unauthorized():\n"
        f"    raise HTTPException(status_code={status_code})\n"
        "from fastapi import FastAPI\napp = FastAPI()\n"
    )
    assert result["status"] == "static_review_passed"
    assert result["findings"][0]["rule"] == "default_http_exception_body"
    assert result["findings"][0]["severity"] == "warning"
    assert result["findings"][0]["category"] == "compatibility"


def test_static_policy_allows_body_bearing_validation_exception():
    result = review_source(
        "from fastapi import HTTPException\n"
        "def invalid():\n"
        '    raise HTTPException(status_code=422, detail={"errors": ["invalid"]})\n'
        "from fastapi import FastAPI\napp = FastAPI()\n"
    )
    assert result["status"] == "static_review_passed"


@pytest.mark.parametrize(
    "registration",
    [
        "@app.exception_handler(HTTPException)\n"
        "def handler(request, exc):\n    return Response()\n",
        "def handler(request, exc):\n    return Response()\n"
        "app.add_exception_handler(HTTPException, handler)\n",
    ],
)
def test_static_policy_defers_custom_error_handler_semantics_to_independent_replay(registration):
    source = (
        "from fastapi import FastAPI, HTTPException, Response\napp = FastAPI()\n"
        "@app.get('/issues/1.json')\ndef denied():\n    raise HTTPException(status_code=403)\n"
        + registration
    )
    review = review_source(source)
    assert review["status"] == "static_review_passed"
    assert review["compatibility_notes"]
    assert review["policy_version"] == "2.4-capability-references"
    prohibited = review_source(source + "import subprocess\n")
    assert prohibited["status"] == "blocked"
    assert "prohibited_capability" in {item["rule"] for item in prohibited["findings"]}


def test_static_policy_does_not_suppress_advisory_for_another_app_or_unrun_registration():
    source = (
        "from fastapi import FastAPI, HTTPException, Response\napp = FastAPI()\n"
        "def denied():\n    raise HTTPException(status_code=403)\n"
        "other = FastAPI()\n@other.exception_handler(HTTPException)\n"
        "def handler(request, exc):\n    return Response()\n"
        "def unused():\n    app.add_exception_handler(HTTPException, handler)\n"
    )
    review = review_source(source)
    assert review["status"] == "static_review_passed"
    assert review["findings"][0]["rule"] == "default_http_exception_body"


def test_compatibility_advisory_never_downgrades_capability_block():
    source = (
        "from fastapi import FastAPI, HTTPException\napp = FastAPI()\n"
        "@app.get('/issues/1.json')\ndef denied():\n    raise HTTPException(status_code=403)\n"
        "import subprocess\n"
    )
    review = review_source(source)
    assert review["status"] == "blocked"
    assert {item["rule"] for item in review["findings"]} == {
        "default_http_exception_body",
        "prohibited_capability",
    }


def test_static_policy_requires_fixture_clock_for_write_routes():
    source = (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        '@app.post("/issues")\n'
        "def create():\n"
        "    return {}\n"
    )
    result = review_source(source)
    assert result["status"] == "blocked"
    assert {finding["rule"] for finding in result["findings"]} == {"fixture_clock_required"}


def test_static_policy_accepts_write_route_that_declares_fixture_clock():
    source = (
        "from pathlib import Path\n"
        "from fastapi import FastAPI\n"
        'app = FastAPI()\nCLOCK_PATH = "/state/clock"\n'
        'fixture_epoch = int(Path(CLOCK_PATH).read_text(encoding="utf-8"))\n'
        '@app.post("/issues")\ndef create():\n    return {"epoch": fixture_epoch}\n'
    )
    assert review_source(source)["status"] == "static_review_passed"


def test_static_policy_recognizes_function_local_fixture_clock_path():
    source = (
        "from pathlib import Path\n"
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "def _clock():\n"
        '    clock_path = Path("/state/clock")\n'
        '    return clock_path.read_text(encoding="utf-8")\n'
        '@app.post("/issues")\n'
        "def create():\n"
        '    return {"clock": _clock()}\n'
    )
    assert review_source(source)["status"] == "static_review_passed"


def test_static_policy_does_not_reuse_clock_alias_from_another_function():
    source = (
        "from pathlib import Path\n"
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "def _unused():\n"
        '    clock_path = Path("/state/clock")\n'
        '@app.post("/issues")\n'
        "def create():\n"
        '    clock_path = Path("/tmp/clock")\n'
        '    return {"clock": clock_path.read_text(encoding="utf-8")}\n'
    )
    assert {finding["rule"] for finding in review_source(source)["findings"]} == {
        "fixture_clock_required"
    }


def test_static_policy_does_not_accept_clock_path_in_a_comment():
    source = (
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "# /state/clock\n"
        '@app.post("/issues")\n'
        "def create():\n"
        "    return {}\n"
    )
    assert {finding["rule"] for finding in review_source(source)["findings"]} == {
        "fixture_clock_required"
    }
