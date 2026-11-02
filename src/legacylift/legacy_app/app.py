"""Small Flask application defining the initial ticket workflow behavior."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, session

from .db import close_db, get_db, initialize_database

MAX_SUBJECT_LENGTH = 120
MAX_DESCRIPTION_LENGTH = 2_000
VALID_STATUSES = {"open", "in_progress", "closed"}
ALLOWED_TRANSITIONS = {"open": "in_progress", "in_progress": "closed"}


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Create the reference app; pass DATABASE to isolate tests and scenarios."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("LEGACYLIFT_SECRET_KEY", "local-development-only"),
        DATABASE=str(Path(app.instance_path) / "legacylift.sqlite3"),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    initialize_database(app.config["DATABASE"])
    app.teardown_appcontext(close_db)

    @app.post("/session")
    def start_test_session():
        payload = request.get_json(silent=True)
        user_id = payload.get("user_id") if isinstance(payload, dict) else None
        if not isinstance(user_id, str) or not user_id.strip() or len(user_id.strip()) > 64:
            return _error("invalid_user_id", "user_id must contain 1 to 64 characters", 400)

        session.clear()
        session["user_id"] = user_id.strip()
        return jsonify({"user_id": session["user_id"]}), 200

    @app.post("/tickets")
    def create_ticket():
        user_id = session.get("user_id")
        if user_id is None:
            return _error("authentication_required", "start a session before creating tickets", 401)

        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return _error("invalid_request", "a JSON object is required", 400)

        subject = payload.get("subject")
        description = payload.get("description", "")
        if not isinstance(subject, str) or not subject.strip():
            return _error("invalid_subject", "subject must not be empty", 400)
        subject = subject.strip()
        if len(subject) > MAX_SUBJECT_LENGTH:
            return _error("invalid_subject", "subject must be at most 120 characters", 400)
        if not isinstance(description, str) or len(description) > MAX_DESCRIPTION_LENGTH:
            return _error("invalid_description", "description must be at most 2000 characters", 400)

        connection = get_db()
        cursor = connection.execute(
            """
            INSERT INTO tickets (owner_id, subject, description, status)
            VALUES (?, ?, ?, 'open')
            """,
            (user_id, subject, description.strip()),
        )
        connection.commit()
        ticket = connection.execute(
            "SELECT id, subject, description, status FROM tickets WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return jsonify(dict(ticket)), 201

    @app.get("/tickets/<int:ticket_id>")
    def get_ticket(ticket_id: int):
        user_id = session.get("user_id")
        if user_id is None:
            return _error(
                "authentication_required", "start a session before retrieving tickets", 401
            )

        ticket = (
            get_db()
            .execute(
                """
            SELECT id, subject, description, status
            FROM tickets
            WHERE id = ? AND owner_id = ?
            """,
                (ticket_id, user_id),
            )
            .fetchone()
        )
        if ticket is None:
            return _error("ticket_not_found", "ticket does not exist", 404)
        return jsonify(dict(ticket))

    @app.patch("/tickets/<int:ticket_id>/status")
    def update_ticket_status(ticket_id: int):
        user_id = session.get("user_id")
        if user_id is None:
            return _error("authentication_required", "start a session before updating tickets", 401)

        payload = request.get_json(silent=True)
        new_status = payload.get("status") if isinstance(payload, dict) else None
        if not isinstance(new_status, str) or new_status not in VALID_STATUSES:
            return _error("invalid_status", "status must be open, in_progress, or closed", 400)

        connection = get_db()
        ticket = connection.execute(
            """
            SELECT id, subject, description, status
            FROM tickets
            WHERE id = ? AND owner_id = ?
            """,
            (ticket_id, user_id),
        ).fetchone()
        if ticket is None:
            return _error("ticket_not_found", "ticket does not exist", 404)
        if ALLOWED_TRANSITIONS.get(ticket["status"]) != new_status:
            return jsonify(
                {
                    "error": "invalid_status_transition",
                    "current_status": ticket["status"],
                    "requested_status": new_status,
                }
            ), 409

        connection.execute(
            "UPDATE tickets SET status = ? WHERE id = ?",
            (new_status, ticket_id),
        )
        connection.commit()
        return jsonify(
            {
                "id": ticket["id"],
                "subject": ticket["subject"],
                "description": ticket["description"],
                "status": new_status,
            }
        )

    return app


def _error(code: str, message: str, status: int):
    return jsonify({"error": code, "message": message}), status
