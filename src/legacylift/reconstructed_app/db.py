"""Independent SQLite storage for the hand-built reconstructed service."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Generator

from fastapi import Request

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id TEXT NOT NULL,
    subject TEXT NOT NULL CHECK(length(subject) BETWEEN 1 AND 120),
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK(status IN ('open', 'in_progress', 'closed'))
);
"""

DEFAULT_TICKETS = (
    (1, "alice", "Synthetic support request", "Fixture ticket for local tests.", "open"),
)


def connect_database(database_path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(database_path), check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(database_path: str | Path) -> None:
    path = Path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_database(path)
    try:
        with connection:
            connection.executescript(SCHEMA)
            if connection.execute("SELECT 1 FROM tickets LIMIT 1").fetchone() is None:
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


def get_db(request: Request) -> Generator[sqlite3.Connection, None, None]:
    connection = connect_database(request.app.state.database_path)
    try:
        yield connection
    finally:
        connection.close()
