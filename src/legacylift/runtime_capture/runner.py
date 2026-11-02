"""Run deterministic scenarios and serialize observed HTTP and SQLite evidence."""

from __future__ import annotations

import json
import sqlite3
from http.cookies import SimpleCookie
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from flask.testing import FlaskClient

from legacylift.legacy_app import create_app
from legacylift.legacy_app.db import reset_database

from .models import TRACE_SCHEMA_VERSION, Scenario
from .scenarios import DEFAULT_SCENARIOS

TRACE_APPLICATION = "legacylift.legacy_app"
TICKET_COLUMNS = ("id", "owner_id", "subject", "description", "status")


def _session_state(client: FlaskClient) -> dict[str, str | None]:
    with client.session_transaction() as flask_session:
        user_id = flask_session.get("user_id")
    return {"user_id": user_id if isinstance(user_id, str) else None}


def snapshot_database(database_path: str | Path) -> list[dict[str, Any]]:
    """Capture only the ticket rows relevant to the selected workflows."""
    connection = sqlite3.connect(str(database_path))
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT id, owner_id, subject, description, status FROM tickets ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def _database_delta(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    before_by_id = {row["id"]: row for row in before}
    after_by_id = {row["id"]: row for row in after}
    added = [after_by_id[key] for key in sorted(after_by_id.keys() - before_by_id.keys())]
    removed = [before_by_id[key] for key in sorted(before_by_id.keys() - after_by_id.keys())]
    updated = [
        {"id": key, "before": before_by_id[key], "after": after_by_id[key]}
        for key in sorted(before_by_id.keys() & after_by_id.keys())
        if before_by_id[key] != after_by_id[key]
    ]
    return {"added": added, "updated": updated, "removed": removed}


def _cookie_metadata(set_cookie_headers: list[str]) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = []
    for header in set_cookie_headers:
        parsed = SimpleCookie()
        parsed.load(header)
        for name, morsel in parsed.items():
            cookies.append(
                {
                    "name": name,
                    "value_redacted": True,
                    "http_only": bool(morsel["httponly"]),
                    "secure": bool(morsel["secure"]),
                    "same_site": morsel["samesite"] or None,
                    "path": morsel["path"] or None,
                }
            )
    return cookies


def _capture_step(client: FlaskClient, database_path: Path, step: Any) -> dict[str, Any]:
    session_before = _session_state(client)
    database_before = snapshot_database(database_path)
    response = client.open(
        step.path,
        method=step.method,
        json=step.json_body,
    )
    session_after = _session_state(client)
    database_after = snapshot_database(database_path)

    set_cookie_headers = response.headers.getlist("Set-Cookie")
    response_headers = {
        name: response.headers[name]
        for name in ("Content-Type", "Vary", "Cache-Control")
        if name in response.headers
    }
    return {
        "step_id": step.step_id,
        "request": {
            "method": step.method,
            "path": step.path,
            "json": step.json_body,
        },
        "response": {
            "status": response.status_code,
            "headers": response_headers,
            "cookies": _cookie_metadata(set_cookie_headers),
            "json": response.get_json(silent=True),
        },
        "session_before": session_before,
        "session_after": session_after,
        "database_before": database_before,
        "database_after": database_after,
        "database_delta": _database_delta(database_before, database_after),
    }


def capture_scenarios(
    scenarios: tuple[Scenario, ...] = DEFAULT_SCENARIOS,
) -> dict[str, Any]:
    """Run each scenario against a fresh database and return a stable trace bundle."""
    traces: list[dict[str, Any]] = []
    with TemporaryDirectory(prefix="legacylift-capture-") as temporary_directory:
        root = Path(temporary_directory)
        for scenario in scenarios:
            database_path = root / f"{scenario.scenario_id}.sqlite3"
            app = create_app(
                {
                    "TESTING": True,
                    "SECRET_KEY": "runtime-capture-test-secret",
                    "DATABASE": str(database_path),
                }
            )
            reset_database(database_path)
            with app.test_client() as client:
                steps = [_capture_step(client, database_path, step) for step in scenario.steps]
            traces.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "description": scenario.description,
                    "steps": steps,
                }
            )

    return {
        "trace_schema_version": TRACE_SCHEMA_VERSION,
        "application": TRACE_APPLICATION,
        "scenarios": traces,
    }


def write_trace_bundle(
    output_path: str | Path,
    scenarios: tuple[Scenario, ...] = DEFAULT_SCENARIOS,
) -> Path:
    """Capture and write a stable, UTF-8 JSON trace bundle."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    bundle = capture_scenarios(scenarios)
    destination.write_text(
        json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination
