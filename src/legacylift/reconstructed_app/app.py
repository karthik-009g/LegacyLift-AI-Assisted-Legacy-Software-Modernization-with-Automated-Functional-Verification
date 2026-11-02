"""FastAPI baseline with independently implemented ticket behavior."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from .db import get_db, initialize_database
from .models import (
    SessionStartRequest,
    SessionStartResponse,
    TicketCreateRequest,
    TicketResponse,
    TicketStatusRequest,
)

ALLOWED_TRANSITIONS = {"open": "in_progress", "in_progress": "closed"}


class _SessionObservationMiddleware:
    """Expose before/after workflow session state to local runners only."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope.get("type") != "http" or not (
            path == "/session" or path == "/tickets" or path.startswith("/tickets/")
        ):
            return await self.app(scope, receive, send)

        scope.setdefault("state", {})["legacylift_session_accessed"] = True
        before = _session_state_from_scope(scope)
        try:
            await self.app(scope, receive, send)
        finally:
            app = scope.get("app")
            callback = getattr(getattr(app, "state", None), "session_observer", None)
            if callback is not None:
                callback({"before": before, "after": _session_state_from_scope(scope)})


class _MatchFlaskSessionCookieMiddleware:
    """Align Starlette's session cookie attributes with the Flask reference app."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def send_with_legacy_cookie(message):
            if message["type"] == "http.response.start":
                headers = []
                session_cookie_written = False
                vary_written = False
                session_accessed = scope.get("state", {}).get("legacylift_session_accessed", False)
                for name, value in message.get("headers", []):
                    if name.lower() == b"set-cookie" and value.lower().startswith(b"session="):
                        value = re.sub(rb";\s*samesite=[^;]+", b"", value, flags=re.IGNORECASE)
                        session_cookie_written = True
                    if name.lower() == b"vary":
                        vary_written = True
                        if b"cookie" not in {part.strip().lower() for part in value.split(b",")}:
                            value += b", Cookie"
                    headers.append((name, value))
                if (session_cookie_written or session_accessed) and not vary_written:
                    headers.append((b"vary", b"Cookie"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_legacy_cookie)


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": code, "message": message}, status_code=status)


def _session_state_from_scope(scope) -> dict[str, str | None]:
    user_id = scope.get("session", {}).get("user_id")
    return {"user_id": user_id if isinstance(user_id, str) else None}


def create_app(test_config: dict[str, Any] | None = None) -> FastAPI:
    config = test_config or {}
    database_path = Path(
        config.get("DATABASE", Path.cwd() / "instance" / "legacylift_reconstructed.sqlite3")
    )
    database_path.parent.mkdir(parents=True, exist_ok=True)
    initialize_database(database_path)

    app = FastAPI(title="LegacyLift Reconstructed Ticket API", version="0.1.0")
    app.state.database_path = database_path
    app.state.session_observer = config.get("SESSION_OBSERVER")
    app.add_middleware(_SessionObservationMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.get(
            "SECRET_KEY", os.environ.get("LEGACYLIFT_SECRET_KEY", "local-development-only")
        ),
        session_cookie="session",
        max_age=None,
        path="/",
        same_site="lax",
        https_only=False,
    )
    app.add_middleware(_MatchFlaskSessionCookieMiddleware)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        locations = {str(item) for issue in error.errors() for item in issue.get("loc", ())}
        if request.url.path == "/session":
            return _error("invalid_user_id", "user_id must contain 1 to 64 characters", 400)
        if request.method == "POST" and request.url.path == "/tickets":
            if "subject" in locations:
                subject_errors = [
                    issue["msg"]
                    for issue in error.errors()
                    if issue.get("loc", ())[-1:] == ("subject",)
                ]
                message = (
                    "subject must be at most 120 characters"
                    if any("at most 120" in item for item in subject_errors)
                    else "subject must not be empty"
                )
                return _error("invalid_subject", message, 400)
            if "description" in locations:
                return _error(
                    "invalid_description", "description must be at most 2000 characters", 400
                )
            return _error("invalid_request", "a JSON object is required", 400)
        if request.method == "PATCH" and request.url.path.endswith("/status"):
            return _error("invalid_status", "status must be open, in_progress, or closed", 400)
        return _error("invalid_request", "request validation failed", 400)

    @app.post("/session", response_model=SessionStartResponse)
    async def start_test_session(payload: SessionStartRequest, request: Request):
        request.session.clear()
        request.session["user_id"] = payload.user_id
        return {"user_id": payload.user_id}

    @app.post("/tickets", response_model=TicketResponse, status_code=201)
    async def create_ticket(
        payload: TicketCreateRequest,
        request: Request,
        connection=Depends(get_db),
    ):
        user_id = request.session.get("user_id")
        if user_id is None:
            return _error("authentication_required", "start a session before creating tickets", 401)

        cursor = connection.execute(
            """
            INSERT INTO tickets (owner_id, subject, description, status)
            VALUES (?, ?, ?, 'open')
            """,
            (user_id, payload.subject, payload.description),
        )
        connection.commit()
        ticket = connection.execute(
            "SELECT id, subject, description, status FROM tickets WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
        return dict(ticket)

    @app.get("/tickets/{ticket_id}", response_model=TicketResponse)
    async def get_ticket(
        ticket_id: int,
        request: Request,
        connection=Depends(get_db),
    ):
        user_id = request.session.get("user_id")
        if user_id is None:
            return _error(
                "authentication_required", "start a session before retrieving tickets", 401
            )

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
        return dict(ticket)

    @app.patch("/tickets/{ticket_id}/status", response_model=TicketResponse)
    async def update_ticket_status(
        ticket_id: int,
        payload: TicketStatusRequest,
        request: Request,
        connection=Depends(get_db),
    ):
        user_id = request.session.get("user_id")
        if user_id is None:
            return _error("authentication_required", "start a session before updating tickets", 401)

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
        if ALLOWED_TRANSITIONS.get(ticket["status"]) != payload.status:
            return JSONResponse(
                {
                    "error": "invalid_status_transition",
                    "current_status": ticket["status"],
                    "requested_status": payload.status,
                },
                status_code=409,
            )

        connection.execute(
            "UPDATE tickets SET status = ? WHERE id = ?",
            (payload.status, ticket_id),
        )
        connection.commit()
        return {
            "id": ticket["id"],
            "subject": ticket["subject"],
            "description": ticket["description"],
            "status": payload.status,
        }

    return app
