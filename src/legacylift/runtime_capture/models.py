"""Versioned data structures used by runtime capture."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

TRACE_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class ScenarioStep:
    """One request in a deterministic workflow scenario."""

    step_id: str
    method: str
    path: str
    json_body: dict[str, Any] | None = None


@dataclass(frozen=True)
class Scenario:
    """An ordered set of requests run against a fresh fixture database."""

    scenario_id: str
    description: str
    steps: tuple[ScenarioStep, ...]
