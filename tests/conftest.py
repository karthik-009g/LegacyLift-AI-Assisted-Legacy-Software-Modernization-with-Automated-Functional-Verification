from __future__ import annotations

import copy
import json
import sqlite3

import pytest
from flask.testing import FlaskClient

from legacylift.legacy_app import create_app
from legacylift.legacy_app.db import reset_database


@pytest.fixture
def app(tmp_path):
    database_path = tmp_path / "legacy.sqlite3"
    application = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-secret",
            "DATABASE": str(database_path),
        }
    )
    reset_database(database_path)
    application.config["TEST_DATABASE_PATH"] = database_path
    return application


@pytest.fixture
def client(app) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def stored_tickets(app):
    def read_all():
        connection = sqlite3.connect(app.config["TEST_DATABASE_PATH"])
        try:
            return connection.execute(
                "SELECT id, owner_id, subject, description, status FROM tickets ORDER BY id"
            ).fetchall()
        finally:
            connection.close()

    return read_all


@pytest.fixture
def frozen_reference_inputs(tmp_path):
    """Complete synthetic contract observations; no real application or model execution."""
    from legacylift.modernization.contracts import canonical_hash, contract_manifest, scenarios

    directory = tmp_path / "study"
    directory.mkdir()
    cases = []
    for specification in scenarios():
        case = copy.deepcopy(specification)
        case["steps"] = [
            {
                "request": request,
                "response": {"status": 200, "headers": {}, "json": {}, "body_bytes": 2},
                "database_before": {},
                "database_after": {},
            }
            for request in case["requests"]
        ]
        cases.append(case)
    oracle = {
        "contract": contract_manifest(),
        "oracle_sha256": canonical_hash(cases),
        "scenarios": cases,
    }
    (directory / "oracle.json").write_text(json.dumps(oracle), encoding="utf-8")
    (directory / "guidance.json").write_text(
        json.dumps({**oracle, "scenarios": [c for c in cases if c["split"] == "guidance"]}),
        encoding="utf-8",
    )
    (directory / "fixture.sqlite3").write_bytes(b"synthetic database")
    (directory / "actors.private.json").write_text(
        '{"actor":"private-actor-marker"}', encoding="utf-8"
    )
    return tmp_path
