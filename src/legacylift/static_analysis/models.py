"""Typed result models for the initial AST analysis pass."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RouteFinding:
    method: str
    path: str
    function: str
    source_file: str
    line: int


@dataclass(frozen=True)
class FunctionFinding:
    name: str
    source_file: str
    line: int
    end_line: int
    calls: tuple[str, ...]
    branch_count: int
    session_references: tuple[str, ...]
    database_operations: tuple[str, ...]


@dataclass(frozen=True)
class AnalysisIssue:
    source_file: str
    line: int | None
    message: str


@dataclass(frozen=True)
class AnalysisReport:
    source_files: tuple[str, ...]
    imports: tuple[str, ...]
    routes: tuple[RouteFinding, ...]
    functions: tuple[FunctionFinding, ...]
    issues: tuple[AnalysisIssue, ...]
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
