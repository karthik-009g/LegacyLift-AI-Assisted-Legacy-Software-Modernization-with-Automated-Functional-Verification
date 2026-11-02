"""Replay fixed scenarios against both apps and report behavioral differences."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from copy import deepcopy
from http.cookies import SimpleCookie
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi.testclient import TestClient
from flask.testing import FlaskClient

from legacylift.legacy_app import create_app as create_legacy_app
from legacylift.legacy_app.db import reset_database as reset_legacy_database
from legacylift.reconstructed_app import create_app as create_reconstructed_app
from legacylift.reconstructed_app.db import reset_database as reset_reconstructed_database
from legacylift.runtime_capture.models import Scenario, ScenarioStep
from legacylift.runtime_capture.scenarios import DEFAULT_SCENARIOS

DIFFERENTIAL_SCHEMA_VERSION = "1.0"
LEGACY_APPLICATION = "legacylift.legacy_app"
RECONSTRUCTED_APPLICATION = "legacylift.reconstructed_app"
TICKET_COLUMNS = ("id", "owner_id", "subject", "description", "status")
COMPARED_FIELDS = (
    "response.status",
    "response.headers",
    "response.cookies",
    "response.json",
    "session_before",
    "session_after",
    "database_before",
    "database_after",
    "database_delta",
)


def snapshot_database(database_path: str | Path) -> list[dict[str, Any]]:
    """Read the ticket state relevant to the selected workflows."""
    connection = sqlite3.connect(str(database_path))
    try:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT id, owner_id, subject, description, status FROM tickets ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    return [dict(row) for row in rows]


def database_delta(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    """Describe inserted, changed, and removed tickets without hiding state changes."""
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


def cookie_metadata(set_cookie_headers: list[str]) -> list[dict[str, Any]]:
    """Keep cookie attributes while excluding signed/session cookie values."""
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


def _capture_flask_step(
    client: FlaskClient, database_path: Path, step: ScenarioStep
) -> dict[str, Any]:
    with client.session_transaction() as flask_session:
        session_before = flask_session.get("user_id")
    database_before = snapshot_database(database_path)
    response = client.open(step.path, method=step.method, json=step.json_body)
    with client.session_transaction() as flask_session:
        session_after = flask_session.get("user_id")
    database_after = snapshot_database(database_path)
    headers = {
        name.lower(): response.headers[name]
        for name in ("Content-Type", "Vary", "Cache-Control")
        if name in response.headers
    }
    return {
        "response": {
            "status": response.status_code,
            "headers": headers,
            "cookies": cookie_metadata(response.headers.getlist("Set-Cookie")),
            "json": response.get_json(silent=True),
        },
        "session_before": {"user_id": session_before if isinstance(session_before, str) else None},
        "session_after": {"user_id": session_after if isinstance(session_after, str) else None},
        "database_before": database_before,
        "database_after": database_after,
        "database_delta": database_delta(database_before, database_after),
    }


def _capture_fastapi_step(
    client: TestClient,
    database_path: Path,
    step: ScenarioStep,
    observations: list[dict[str, dict[str, str | None]]],
) -> dict[str, Any]:
    observations.clear()
    database_before = snapshot_database(database_path)
    response = client.request(step.method, step.path, json=step.json_body)
    database_after = snapshot_database(database_path)
    if len(observations) != 1:
        raise RuntimeError(
            f"Expected one session observation for {step.method} {step.path}, "
            f"received {len(observations)}"
        )

    headers = {
        name: response.headers[name]
        for name in ("content-type", "vary", "cache-control")
        if name in response.headers
    }
    try:
        response_json = response.json()
    except (ValueError, json.JSONDecodeError):
        response_json = None
    return {
        "response": {
            "status": response.status_code,
            "headers": headers,
            "cookies": cookie_metadata(response.headers.get_list("set-cookie")),
            "json": response_json,
        },
        "session_before": observations[0]["before"],
        "session_after": observations[0]["after"],
        "database_before": database_before,
        "database_after": database_after,
        "database_delta": database_delta(database_before, database_after),
    }


def compare_observations(
    legacy: dict[str, Any], reconstructed: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return explicit field-level mismatches between two captured steps."""
    mismatches = []
    for field in COMPARED_FIELDS:
        value: Any = legacy
        for component in field.split("."):
            value = value[component]
        reconstructed_value: Any = reconstructed
        for component in field.split("."):
            reconstructed_value = reconstructed_value[component]
        if value != reconstructed_value:
            mismatches.append(
                {
                    "field": field,
                    "legacy": value,
                    "reconstructed": reconstructed_value,
                }
            )
    return mismatches


def _make_step_result(
    step: ScenarioStep, legacy: dict[str, Any], reconstructed: dict[str, Any]
) -> dict[str, Any]:
    mismatches = compare_observations(legacy, reconstructed)
    return {
        "step_id": step.step_id,
        "request": {
            "method": step.method,
            "path": step.path,
            "json": step.json_body,
        },
        "passed": not mismatches,
        "mismatches": mismatches,
        "legacy": legacy,
        "reconstructed": reconstructed,
    }


def _prepare_apps(
    root: Path,
    scenario: Scenario,
    observations: list[dict[str, dict[str, str | None]]],
    reconstructed_app_factory: Callable[[dict[str, Any]], Any],
):
    legacy_database = root / f"{scenario.scenario_id}-legacy.sqlite3"
    reconstructed_database = root / f"{scenario.scenario_id}-reconstructed.sqlite3"
    legacy_app = create_legacy_app(
        {
            "TESTING": True,
            "SECRET_KEY": "differential-test-secret",
            "DATABASE": str(legacy_database),
        }
    )
    reconstructed_app = reconstructed_app_factory(
        {
            "SECRET_KEY": "differential-test-secret",
            "DATABASE": reconstructed_database,
            "SESSION_OBSERVER": observations.append,
        }
    )
    reset_legacy_database(legacy_database)
    reset_reconstructed_database(reconstructed_database)
    return legacy_app, legacy_database, reconstructed_app, reconstructed_database


def compare_scenarios(
    scenarios: tuple[Scenario, ...] = DEFAULT_SCENARIOS,
    *,
    reconstructed_app_factory: Callable[[dict[str, Any]], Any] = create_reconstructed_app,
    reconstructed_application: str = RECONSTRUCTED_APPLICATION,
) -> dict[str, Any]:
    """Replay scenarios against Flask and a supplied FastAPI app factory."""
    scenario_results = []
    with TemporaryDirectory(prefix="legacylift-differential-") as temporary_directory:
        root = Path(temporary_directory)
        for scenario in scenarios:
            observations: list[dict[str, dict[str, str | None]]] = []
            (
                legacy_app,
                legacy_database,
                reconstructed_app,
                reconstructed_database,
            ) = _prepare_apps(root, scenario, observations, reconstructed_app_factory)
            step_results = []
            with (
                legacy_app.test_client() as legacy_client,
                TestClient(reconstructed_app) as reconstructed_client,
            ):
                for step in scenario.steps:
                    legacy = _capture_flask_step(legacy_client, legacy_database, step)
                    reconstructed = _capture_fastapi_step(
                        reconstructed_client,
                        reconstructed_database,
                        step,
                        observations,
                    )
                    step_results.append(_make_step_result(step, legacy, reconstructed))
            scenario_results.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "description": scenario.description,
                    "passed": all(step["passed"] for step in step_results),
                    "steps": step_results,
                }
            )

    steps = [step for scenario in scenario_results for step in scenario["steps"]]
    passed_steps = sum(step["passed"] for step in steps)
    return {
        "differential_schema_version": DIFFERENTIAL_SCHEMA_VERSION,
        "legacy_application": LEGACY_APPLICATION,
        "reconstructed_application": reconstructed_application,
        "summary": {
            "passed": passed_steps == len(steps),
            "scenario_count": len(scenario_results),
            "step_count": len(steps),
            "passed_step_count": passed_steps,
            "failed_step_count": len(steps) - passed_steps,
        },
        "scenarios": scenario_results,
    }


def write_differential_report(
    output_path: str | Path,
    scenarios: tuple[Scenario, ...] = DEFAULT_SCENARIOS,
) -> Path:
    """Run differential verification and write a stable UTF-8 JSON report."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    report = compare_scenarios(scenarios)
    destination.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination


def sample_mismatch_report() -> dict[str, Any]:
    """Create a labeled mismatch example by mutating one captured result in memory."""
    scenario = DEFAULT_SCENARIOS[0]
    report = compare_scenarios((scenario,))
    baseline_step = report["scenarios"][0]["steps"][0]
    legacy = baseline_step["legacy"]
    reconstructed = deepcopy(baseline_step["reconstructed"])
    reconstructed["response"]["status"] = 418
    mismatches = compare_observations(legacy, reconstructed)
    return {
        "differential_schema_version": DIFFERENTIAL_SCHEMA_VERSION,
        "report_kind": "synthetic_mutation_example",
        "note": (
            "This is not an observed failure. The reconstructed status was changed in memory "
            "to demonstrate the mismatch report format."
        ),
        "scenario_id": scenario.scenario_id,
        "step_id": baseline_step["step_id"],
        "request": baseline_step["request"],
        "passed": not mismatches,
        "mismatches": mismatches,
        "legacy": legacy,
        "reconstructed": reconstructed,
    }


def write_sample_mismatch_report(output_path: str | Path) -> Path:
    """Write the synthetic mismatch example used in the project documentation."""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(sample_mismatch_report(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return destination
