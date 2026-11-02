from __future__ import annotations

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
