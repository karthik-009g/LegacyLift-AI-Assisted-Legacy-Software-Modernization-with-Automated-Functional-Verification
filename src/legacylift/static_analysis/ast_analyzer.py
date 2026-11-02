"""Extract literal route declarations and selected code references without execution."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

from .models import AnalysisIssue, AnalysisReport, FunctionFinding, RouteFinding

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
ANALYSIS_LIMITATIONS = (
    "Only Python syntax and literal Flask route decorators are inspected; "
    "application code is never executed.",
    "Dynamic route registration, reflection, runtime dispatch, external services, "
    "and unvisited paths are not resolved.",
)


class _FunctionVisitor(ast.NodeVisitor):
    def __init__(self, root: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.root = root
        self.calls: set[str] = set()
        self.branches = 0
        self.session_references: set[str] = set()
        self.database_operations: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            for child in node.body:
                self.visit(child)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            for child in node.body:
                self.visit(child)

    def visit_Call(self, node: ast.Call) -> None:
        call_name = ast.unparse(node.func)
        self.calls.add(call_name)
        if (
            call_name == "get_db"
            or call_name.endswith(".execute")
            or call_name.endswith(".executemany")
            or call_name.endswith(".commit")
            or call_name.endswith(".connect")
        ):
            self.database_operations.add(call_name)
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_Match(self, node: ast.Match) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.branches += 1
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id == "session":
            self.session_references.add("session")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr == "session":
            self.session_references.add("session")
        self.generic_visit(node)


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _literal_route(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "app":
            continue
        if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
            continue
        route_path = decorator.args[0].value
        if not isinstance(route_path, str):
            continue

        attribute = decorator.func.attr.lower()
        if attribute == "route":
            methods: set[str] = {"GET"}
            for keyword in decorator.keywords:
                if keyword.arg == "methods" and isinstance(keyword.value, (ast.List, ast.Tuple)):
                    methods = {
                        item.value.upper()
                        for item in keyword.value.elts
                        if isinstance(item, ast.Constant)
                        and isinstance(item.value, str)
                        and item.value.upper() in HTTP_METHODS
                    }
            findings.extend((method, route_path) for method in sorted(methods))
        elif attribute.upper() in HTTP_METHODS:
            findings.append((attribute.upper(), route_path))
    return findings


def _source_files(paths: Iterable[str | Path]) -> list[Path]:
    files: set[Path] = set()
    for input_path in paths:
        path = Path(input_path)
        if path.is_dir():
            files.update(
                candidate
                for candidate in path.rglob("*.py")
                if "__pycache__" not in candidate.parts
            )
        elif path.is_file() and path.suffix == ".py":
            files.add(path)
    return sorted(files, key=lambda item: item.as_posix().casefold())


def analyze_paths(
    paths: Iterable[str | Path],
    *,
    root: str | Path | None = None,
) -> AnalysisReport:
    """Analyze Python files or directories, reporting parse errors as partial findings."""
    source_paths = _source_files(paths)
    if root is None:
        root_path = Path.cwd()
    else:
        root_path = Path(root)

    imports: set[str] = set()
    routes: list[RouteFinding] = []
    functions: list[FunctionFinding] = []
    issues: list[AnalysisIssue] = []
    relative_files: list[str] = []

    for source_path in source_paths:
        relative_file = _relative_path(source_path, root_path)
        relative_files.append(relative_file)
        try:
            source = source_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative_file)
        except (OSError, UnicodeError, SyntaxError) as error:
            issues.append(
                AnalysisIssue(
                    source_file=relative_file,
                    line=getattr(error, "lineno", None),
                    message=f"{type(error).__name__}: {error}",
                )
            )
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add("." * node.level + (node.module or ""))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for method, route_path in _literal_route(node):
                    routes.append(
                        RouteFinding(
                            method=method,
                            path=route_path,
                            function=node.name,
                            source_file=relative_file,
                            line=node.lineno,
                        )
                    )
                visitor = _FunctionVisitor(node)
                visitor.visit(node)
                functions.append(
                    FunctionFinding(
                        name=node.name,
                        source_file=relative_file,
                        line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                        calls=tuple(sorted(visitor.calls)),
                        branch_count=visitor.branches,
                        session_references=tuple(sorted(visitor.session_references)),
                        database_operations=tuple(sorted(visitor.database_operations)),
                    )
                )

    return AnalysisReport(
        source_files=tuple(sorted(relative_files)),
        imports=tuple(sorted(imports)),
        routes=tuple(sorted(routes, key=lambda item: (item.source_file, item.line, item.method))),
        functions=tuple(
            sorted(functions, key=lambda item: (item.source_file, item.line, item.name))
        ),
        issues=tuple(sorted(issues, key=lambda item: (item.source_file, item.line or 0))),
        limitations=ANALYSIS_LIMITATIONS,
    )
