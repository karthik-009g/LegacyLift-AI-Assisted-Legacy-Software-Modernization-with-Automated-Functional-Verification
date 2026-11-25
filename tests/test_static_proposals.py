from __future__ import annotations

import hashlib
import json
from pathlib import Path

from legacylift.evaluation.static_review import inspect_proposals
from legacylift.evidence.storage import load_eer
from legacylift.reconstruction.context import build_reconstruction_request
from legacylift.reconstruction.prompts import build_reconstruction_prompt


def _write_proposal(directory: Path, condition: str, code: str, prompt_sha256: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    proposal = {
        "provider": "test-provider",
        "condition": condition,
        "summary": "Static inspection test fixture",
        "evidence_ids": [],
        "proposed_code": code,
        "requires_human_review": True,
        "prompt_sha256": prompt_sha256,
    }
    (directory / f"{condition}.json").write_text(json.dumps(proposal), encoding="utf-8")


def _current_prompt_hash(project_root: Path, condition: str) -> str:
    record = load_eer(project_root / "artifacts" / "evaluation" / "guidance_eer.json")
    request = build_reconstruction_request(record, condition, source_root=project_root)
    return hashlib.sha256(build_reconstruction_prompt(request).encode("utf-8")).hexdigest()


def test_static_inspector_rejects_stale_code_without_executing_it(tmp_path):
    project_root = Path(__file__).parents[1]
    proposal_directory = tmp_path / "proposals"
    _write_proposal(
        proposal_directory,
        "runtime_only",
        "import subprocess\nsubprocess.run(['never-run'])\n",
        "0" * 64,
    )

    report = inspect_proposals(
        project_root,
        proposals_directory=proposal_directory,
        output_path=tmp_path / "static-review.json",
    )

    result = report["conditions"]["runtime_only"]
    assert report["mode"] == "static_only"
    assert report["candidate_code_executed"] is False
    assert report["functional_evaluation"] == "not_run"
    assert result["status"] == "stale_prompt"
    assert result["manual_review_flags"] == ["call:subprocess.run", "import:subprocess"]
    assert result["code_executed"] is False


def test_static_inspector_accepts_current_prompt_for_syntax_preflight(tmp_path):
    project_root = Path(__file__).parents[1]
    proposal_directory = tmp_path / "proposals"
    _write_proposal(
        proposal_directory,
        "source_only",
        "from fastapi import FastAPI\n\ndef create_app(test_config=None):\n    return FastAPI()\n",
        _current_prompt_hash(project_root, "source_only"),
    )

    report = inspect_proposals(
        project_root,
        proposals_directory=proposal_directory,
        output_path=tmp_path / "static-review.json",
    )

    result = report["conditions"]["source_only"]
    assert result["status"] == "static_checks_passed"
    assert result["prompt_current"] is True
    assert result["imports"] == ["fastapi"]
    assert report["static_review_schema_version"] == "1.1"
    assert report["functional_evaluation"] == "not_run"


def test_static_inspector_accepts_guarded_session_and_status_patterns(tmp_path):
    project_root = Path(__file__).parents[1]
    proposal_directory = tmp_path / "proposals"
    code = """
from fastapi.middleware.sessions import SessionMiddleware

ALLOWED_TRANSITIONS = {"open": "in_progress", "in_progress": "closed"}

async def session_observer_middleware(request, call_next):
    before = request.session.get("user_id")
    response = await call_next(request)
    after = request.session.get("user_id")
    request.app.state.observer({"before": before, "after": after})
    return response

def create_app(app):
    app.middleware("http")(session_observer_middleware)
    app.add_middleware(SessionMiddleware, secret_key="test")
    return app

@app.post("/session")
def start_session(request, user_id):
    request.session["user_id"] = user_id
    return {"user_id": user_id}

@app.get("/tickets/{ticket_id}")
def get_ticket(request, ticket_id, db):
    user_id = request.session.get("user_id")
    if user_id is None:
        raise ValueError("authentication required")
    return db.execute(
        "SELECT * FROM tickets WHERE id = ? AND owner_id = ?", (ticket_id, user_id)
    ).fetchone()

def update_ticket_status(request, ticket_id, payload, db):
    user_id = request.session.get("user_id")
    row = db.execute(
        "SELECT * FROM tickets WHERE id = ? AND owner_id = ?", (ticket_id, user_id)
    ).fetchone()
    requested_status = payload.status
    if ALLOWED_TRANSITIONS.get(row["status"]) != requested_status:
        raise ValueError("invalid transition")
    db.execute(
        "UPDATE tickets SET status = ? WHERE id = ? AND owner_id = ?",
        (requested_status, ticket_id, user_id),
    )
"""
    _write_proposal(
        proposal_directory,
        "hybrid",
        code,
        _current_prompt_hash(project_root, "hybrid"),
    )

    report = inspect_proposals(
        project_root,
        proposals_directory=proposal_directory,
        output_path=tmp_path / "static-review.json",
    )

    result = report["conditions"]["hybrid"]
    assert result["status"] == "static_checks_passed"
    assert result["manual_review_flags"] == []


def test_static_inspector_reports_syntax_errors_without_execution(tmp_path):
    project_root = Path(__file__).parents[1]
    proposal_directory = tmp_path / "proposals"
    _write_proposal(proposal_directory, "hybrid", "def create_app(:\n", "0" * 64)

    report = inspect_proposals(
        project_root,
        proposals_directory=proposal_directory,
        output_path=tmp_path / "static-review.json",
    )

    result = report["conditions"]["hybrid"]
    assert result["status"] == "syntax_error"
    assert result["syntax_error"]["line"] == 1
    assert result["code_executed"] is False


def test_static_inspector_flags_database_ownership_middleware_and_cookie_patterns(tmp_path):
    project_root = Path(__file__).parents[1]
    proposal_directory = tmp_path / "proposals"
    code = """
import sqlite3
from fastapi.responses import JSONResponse
from fastapi.middleware.sessions import SessionMiddleware

def observer(request, call_next):
    return call_next(request)

def get_ticket(db):
    return db.execute("SELECT * FROM tickets WHERE id = ?", (1,)).fetchone()

def set_session(response):
    response.set_cookie("session", "value")

@app.post("/session")
def start_session(response):
    set_session(response)
    return JSONResponse({})

def notify_observer(observer, before, after):
    observer(before, after)

async def session_observer_middleware(request, call_next):
    before = request.session.get("user_id")
    response = await call_next(request)
    after = request.session.get("user_id")
    return response

def update_ticket_status(db, ticket_id, new_status):
    return db.execute("UPDATE tickets SET status = ? WHERE id = ?", (new_status, ticket_id))

def create_app(app, observer):
    app.add_middleware(SessionMiddleware, secret_key="test")
    app.middleware("http")(session_observer_middleware)
    return app

connection = sqlite3.connect(":memory:")
"""
    _write_proposal(
        proposal_directory,
        "hybrid",
        code,
        _current_prompt_hash(project_root, "hybrid"),
    )
    for condition in ("source_only", "runtime_only"):
        _write_proposal(
            proposal_directory,
            condition,
            "def create_app(test_config=None):\n    return object()\n",
            _current_prompt_hash(project_root, condition),
        )

    report = inspect_proposals(
        project_root,
        proposals_directory=proposal_directory,
        output_path=tmp_path / "static-review.json",
    )

    flags = report["conditions"]["hybrid"]["manual_review_flags"]
    assert report["conditions"]["hybrid"]["status"] == "manual_review_required"
    assert report["status"] == "manual_review_required"
    assert "database_lifecycle:sqlite_memory_database_literal" in flags
    assert "async_middleware:sync_call_next:observer" in flags
    assert "ownership:ticket_read_may_not_filter_owner:get_ticket" in flags
    assert "authentication:ticket_read_may_not_require_session:get_ticket" in flags
    assert "session_cookie:verify_returned_response:start_session" in flags
    assert "session_observer:verify_start_session_after_state:start_session" in flags
    assert "session_observer:verify_single_argument:notify_observer" in flags
    assert "status_transition:verify_current_state_guard:update_ticket_status" in flags
    assert "ownership:verify_status_update_owner:update_ticket_status" in flags
    assert "middleware_order:review_session_observer_registration:create_app" in flags
    assert "session_observer:verify_single_argument:create_app" not in flags


def test_static_cli_returns_success_when_manual_review_is_required(monkeypatch, capsys):
    from legacylift import cli

    monkeypatch.setattr(
        cli,
        "inspect_proposals",
        lambda *_args, **_kwargs: {"status": "manual_review_required"},
    )

    assert cli.main(["inspect-proposals"]) == 0
    assert '"status": "manual_review_required"' in capsys.readouterr().out
