"""SQLite setup and request-scoped connections for the legacy reference app."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id TEXT NOT NULL,
    subject TEXT NOT NULL CHECK(length(subject) BETWEEN 1 AND 120),
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('open', 'in_progress', 'closed'))
);
"""

# Synthetic, deterministic data. IDs are explicit so scenarios are repeatable.
DEFAULT_TICKETS = (
    (1, "alice", "Synthetic support request", "Fixture ticket for local tests.", "open"),
)


def connect_database(database_path: str | Path) -> sqlite3.Connection:
    """Return a SQLite connection that returns rows by column name."""
    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path: str | Path) -> None:
    """Create the schema and seed fixtures only when the database is empty."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_database(path)
    try:
        with connection:
            connection.executescript(SCHEMA)
            has_tickets = connection.execute("SELECT 1 FROM tickets LIMIT 1").fetchone()
            if has_tickets is None:
                connection.executemany(
                    """
                    INSERT INTO tickets (id, owner_id, subject, description, status)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    DEFAULT_TICKETS,
                )
    finally:
        connection.close()


def reset_database(
    database_path: str | Path,
    tickets: tuple[tuple[int, str, str, str, str], ...] = DEFAULT_TICKETS,
) -> None:
    """Recreate the database from deterministic synthetic ticket fixtures."""
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_database(path)
    try:
        with connection:
            connection.execute("DROP TABLE IF EXISTS tickets")
            connection.executescript(SCHEMA)
            connection.executemany(
                """
                INSERT INTO tickets (id, owner_id, subject, description, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                tickets,
            )
    finally:
        connection.close()


def get_db() -> sqlite3.Connection:
    """Get or create this Flask application context's database connection."""
    if "database" not in g:
        g.database = connect_database(current_app.config["DATABASE"])
    return g.database


def close_db(_error: BaseException | None = None) -> None:
    """Close the request-scoped connection when the application context ends."""
    connection = g.pop("database", None)
    if connection is not None:
        connection.close()
