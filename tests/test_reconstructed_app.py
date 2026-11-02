from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from legacylift.reconstructed_app import create_app
from legacylift.reconstructed_app.db import reset_database


def make_client(tmp_path, session_observer=None):
    database_path = tmp_path / "reconstructed.sqlite3"
    app = create_app(
        {
            "DATABASE": database_path,
            "SECRET_KEY": "test-secret",
            "SESSION_OBSERVER": session_observer,
        }
    )
    reset_database(database_path)
    return app, TestClient(app), database_path


def read_tickets(database_path):
    connection = sqlite3.connect(database_path)
    try:
        return connection.execute(
            "SELECT id, owner_id, subject, description, status FROM tickets ORDER BY id"
        ).fetchall()
    finally:
        connection.close()


def test_reconstructed_create_matches_legacy_validation_and_persistence(tmp_path):
    _, client, database_path = make_client(tmp_path)
    assert client.post("/tickets", json={"subject": "Ticket"}).status_code == 401
    assert client.post("/session", json={"user_id": "alice"}).status_code == 200

    created = client.post(
        "/tickets",
        json={"subject": "  New support request  ", "description": "  Please investigate.  "},
    )

    assert created.status_code == 201
    assert created.json() == {
        "id": 2,
        "subject": "New support request",
        "description": "Please investigate.",
        "status": "open",
    }
    assert read_tickets(database_path)[1] == (
        2,
        "alice",
        "New support request",
        "Please investigate.",
        "open",
    )


def test_reconstructed_invalid_input_uses_legacy_status_and_error_contracts(tmp_path):
    _, client, database_path = make_client(tmp_path)

    invalid_session = client.post("/session", json={"user_id": " "})
    assert invalid_session.status_code == 400
    assert invalid_session.json() == {
        "error": "invalid_user_id",
        "message": "user_id must contain 1 to 64 characters",
    }

    client.post("/session", json={"user_id": "alice"})
    empty_subject = client.post("/tickets", json={"subject": "  "})
    long_subject = client.post("/tickets", json={"subject": "x" * 121})
    long_description = client.post(
        "/tickets", json={"subject": "Valid", "description": "x" * 2_001}
    )

    assert empty_subject.json() == {
        "error": "invalid_subject",
        "message": "subject must not be empty",
    }
    assert long_subject.json() == {
        "error": "invalid_subject",
        "message": "subject must be at most 120 characters",
    }
    assert long_description.json() == {
        "error": "invalid_description",
        "message": "description must be at most 2000 characters",
    }
    assert (
        empty_subject.status_code == long_subject.status_code == long_description.status_code == 400
    )
    assert len(read_tickets(database_path)) == 1


def test_reconstructed_owner_check_and_session_observer(tmp_path):
    observations = []
    _, client, _ = make_client(tmp_path, observations.append)

    owner_login = client.post("/session", json={"user_id": "alice"})
    own_ticket = client.get("/tickets/1")
    client.post("/session", json={"user_id": "bob"})
    other_users_ticket = client.get("/tickets/1")

    assert owner_login.status_code == own_ticket.status_code == 200
    assert other_users_ticket.status_code == 404
    assert other_users_ticket.json() == {
        "error": "ticket_not_found",
        "message": "ticket does not exist",
    }
    assert observations[0] == {
        "before": {"user_id": None},
        "after": {"user_id": "alice"},
    }


def test_reconstructed_status_transitions_persist_and_reject_invalid_jump(tmp_path):
    _, client, database_path = make_client(tmp_path)
    client.post("/session", json={"user_id": "alice"})

    skipped = client.patch("/tickets/1/status", json={"status": "closed"})
    assert skipped.status_code == 409
    assert read_tickets(database_path)[0][4] == "open"

    started = client.patch("/tickets/1/status", json={"status": "in_progress"})
    closed = client.patch("/tickets/1/status", json={"status": "closed"})

    assert started.status_code == closed.status_code == 200
    assert started.json()["status"] == "in_progress"
    assert closed.json()["status"] == "closed"
    assert read_tickets(database_path)[0][4] == "closed"


def test_reconstructed_rejects_malformed_request_json(tmp_path):
    _, client, _ = make_client(tmp_path)

    response = client.post("/tickets", content="{bad", headers={"content-type": "application/json"})

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"
