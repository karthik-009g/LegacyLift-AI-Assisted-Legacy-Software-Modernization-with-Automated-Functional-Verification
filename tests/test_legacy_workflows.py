from __future__ import annotations

from legacylift.legacy_app.db import reset_database


def test_create_ticket_requires_session_and_persists_valid_input(client, stored_tickets):
    payload = {"subject": "  New support request  ", "description": "  Please investigate.  "}

    assert client.post("/tickets", json=payload).status_code == 401

    client.post("/session", json={"user_id": "alice"})
    response = client.post("/tickets", json=payload)

    assert response.status_code == 201
    assert response.json == {
        "id": 2,
        "subject": "New support request",
        "description": "Please investigate.",
        "status": "open",
    }
    assert stored_tickets()[1] == (
        2,
        "alice",
        "New support request",
        "Please investigate.",
        "open",
    )


def test_create_ticket_rejects_invalid_subject_and_description(client, stored_tickets):
    client.post("/session", json={"user_id": "alice"})

    empty_subject = client.post("/tickets", json={"subject": "  "})
    long_subject = client.post("/tickets", json={"subject": "x" * 121})
    long_description = client.post(
        "/tickets",
        json={"subject": "Valid subject", "description": "x" * 2_001},
    )

    assert empty_subject.status_code == 400
    assert empty_subject.json["error"] == "invalid_subject"
    assert long_subject.status_code == 400
    assert long_description.status_code == 400
    assert len(stored_tickets()) == 1


def test_ticket_retrieval_is_limited_to_the_session_owner(client):
    client.post("/session", json={"user_id": "alice"})
    own_ticket = client.get("/tickets/1")
    assert own_ticket.status_code == 200
    assert own_ticket.json["subject"] == "Synthetic support request"

    client.post("/session", json={"user_id": "bob"})
    other_users_ticket = client.get("/tickets/1")

    assert other_users_ticket.status_code == 404
    assert other_users_ticket.json["error"] == "ticket_not_found"


def test_ticket_retrieval_rejects_missing_session_and_unknown_ticket(client):
    assert client.get("/tickets/1").status_code == 401

    client.post("/session", json={"user_id": "alice"})
    assert client.get("/tickets/999").status_code == 404


def test_status_transition_rules_and_database_state(client, stored_tickets):
    client.post("/session", json={"user_id": "alice"})

    skipped_state = client.patch("/tickets/1/status", json={"status": "closed"})
    assert skipped_state.status_code == 409
    assert skipped_state.json["current_status"] == "open"
    assert stored_tickets()[0][4] == "open"

    in_progress = client.patch("/tickets/1/status", json={"status": "in_progress"})
    closed = client.patch("/tickets/1/status", json={"status": "closed"})

    assert in_progress.status_code == 200
    assert in_progress.json["status"] == "in_progress"
    assert closed.status_code == 200
    assert closed.json["status"] == "closed"
    assert stored_tickets()[0][4] == "closed"


def test_status_transition_rejects_unknown_status(client, stored_tickets):
    client.post("/session", json={"user_id": "alice"})

    response = client.patch("/tickets/1/status", json={"status": "reopened"})

    assert response.status_code == 400
    assert response.json["error"] == "invalid_status"
    assert stored_tickets()[0][4] == "open"


def test_reset_database_restores_the_synthetic_fixture(app, client, stored_tickets):
    client.post("/session", json={"user_id": "alice"})
    client.patch("/tickets/1/status", json={"status": "in_progress"})
    client.post("/tickets", json={"subject": "Temporary"})

    reset_database(app.config["TEST_DATABASE_PATH"])

    assert stored_tickets() == [
        (1, "alice", "Synthetic support request", "Fixture ticket for local tests.", "open")
    ]
