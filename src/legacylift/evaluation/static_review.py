"""Check proposal schema, prompt freshness, and Python syntax without execution."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from legacylift.reconstruction.models import ReconstructionProposal

from .reviewed import (
    CONDITIONS,
    DEFAULT_PROPOSALS,
    _expected_prompt_sha256,
    _sha256,
)

DEFAULT_STATIC_REPORT = DEFAULT_PROPOSALS / "static_review.json"

_REVIEW_IMPORT_ROOTS = {
    "ftplib",
    "httpx",
    "requests",
    "socket",
    "subprocess",
    "telnetlib",
    "urllib",
}
_REVIEW_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "open",
    "system",
    "popen",
    "Popen",
    "read_text",
    "write_text",
    "unlink",
}
_REVIEW_QUALIFIED_CALLS = {"os.system", "os.popen", "subprocess.run"}
_OBSERVER_CALLBACK_NAMES = {"observer", "session_observer", "sessionobserver"}


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


def _function_scope(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.AST]:
    """Walk one function body without attributing nested functions to its scope."""
    pending = list(node.body)
    result: list[ast.AST] = []
    while pending:
        current = pending.pop()
        result.append(current)
        if isinstance(
            current,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
        ):
            continue
        pending.extend(ast.iter_child_nodes(current))
    return result


def _is_session_route(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        if (_dotted_name(decorator.func) or "").rsplit(".", 1)[-1] not in {"post", "route"}:
            continue
        if any(isinstance(arg, ast.Constant) and arg.value == "/session" for arg in decorator.args):
            return True
    return False


def _writes_session_user_id(node: ast.AST) -> bool:
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store):
        return (
            isinstance(node.slice, ast.Constant)
            and node.slice.value == "user_id"
            and _dotted_name(node.value) == "request.session"
        )
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Store)
        and node.attr == "user_id"
        and _dotted_name(node.value) == "request.state"
    )


def _is_current_status_reference(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id.lower() in {
            "current_status",
            "existing_status",
            "old_status",
            "previous_status",
            "stored_status",
        }
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == "status"
        and isinstance(node.value, ast.Name)
        and node.value.id.lower() in {"row", "ticket", "existing_ticket", "current_ticket"}
    )


def _is_requested_status_reference(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id.lower() in {"new_status", "next_status", "requested_status", "target_status"}
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "status"
        and isinstance(node.value, ast.Name)
        and node.value.id.lower() in {"payload", "body", "request_data"}
    )


def _is_session_middleware_registration(node: ast.Call) -> bool:
    return (
        (_dotted_name(node.func) or "").endswith(".add_middleware")
        and bool(node.args)
        and _dotted_name(node.args[0]) == "SessionMiddleware"
    )


def _registered_session_observer(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Call):
        return False
    middleware_factory = node.func
    if (_dotted_name(middleware_factory.func) or "").rsplit(".", 1)[-1] != "middleware":
        return False
    if not middleware_factory.args or not (
        isinstance(middleware_factory.args[0], ast.Constant)
        and middleware_factory.args[0].value == "http"
    ):
        return False
    return any(
        isinstance(argument, ast.Name)
        and ("observer" in argument.id.lower() or "session" in argument.id.lower())
        for argument in node.args
    )


def _static_findings(tree: ast.Module) -> tuple[list[str], list[str]]:
    imports: set[str] = set()
    flags: set[str] = set()
    functions = [
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    nodes = list(ast.walk(tree))
    if any(isinstance(node, ast.Constant) and node.value == ":memory:" for node in nodes):
        flags.add("database_lifecycle:sqlite_memory_database_literal")

    for node in nodes:
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
        elif isinstance(node, ast.Call):
            call_name = _dotted_name(node.func)
            if call_name and (
                call_name.rsplit(".", 1)[-1] in _REVIEW_CALLS
                or call_name in _REVIEW_QUALIFIED_CALLS
            ):
                flags.add(f"call:{call_name}")

    for module in imports:
        if module.split(".", 1)[0] in _REVIEW_IMPORT_ROOTS:
            flags.add(f"import:{module}")

    scoped_functions = {function: _function_scope(function) for function in functions}
    call_names_by_function = {
        function: [
            _dotted_name(node.func) or "" for node in scoped_nodes if isinstance(node, ast.Call)
        ]
        for function, scoped_nodes in scoped_functions.items()
    }
    setter_functions = {
        function.name
        for function, call_names in call_names_by_function.items()
        if any(name.endswith(".set_cookie") for name in call_names)
    }
    observer_middleware_reads_session_before_next = any(
        "middleware" in function.name.lower()
        and ("observer" in function.name.lower() or "session" in function.name.lower())
        and any(name.rsplit(".", 1)[-1] == "call_next" for name in call_names)
        and any(
            isinstance(node, ast.Attribute)
            and node.attr == "session"
            and isinstance(node.value, ast.Name)
            and node.value.id == "request"
            and node.lineno
            < min(
                call.lineno
                for call in scoped_functions[function]
                if isinstance(call, ast.Call)
                and (_dotted_name(call.func) or "").rsplit(".", 1)[-1] == "call_next"
            )
            for node in scoped_functions[function]
        )
        for function, call_names in call_names_by_function.items()
    )
    for function in functions:
        scoped_nodes = scoped_functions[function]
        calls = [node for node in scoped_nodes if isinstance(node, ast.Call)]

        call_next_calls = [
            node
            for node in calls
            if (_dotted_name(node.func) or "").rsplit(".", 1)[-1] == "call_next"
        ]
        if call_next_calls:
            if isinstance(function, ast.AsyncFunctionDef):
                awaited_calls = {
                    id(node.value) for node in scoped_nodes if isinstance(node, ast.Await)
                }
                if any(id(call) not in awaited_calls for call in call_next_calls):
                    flags.add(f"async_middleware:unawaited_call_next:{function.name}")
            else:
                flags.add(f"async_middleware:sync_call_next:{function.name}")

        for call in calls:
            call_name = _dotted_name(call.func) or ""
            callback_name = call_name.rsplit(".", 1)[-1].lower()
            if callback_name in _OBSERVER_CALLBACK_NAMES and len(call.args) != 1:
                flags.add(f"session_observer:verify_single_argument:{function.name}")

        string_literals = [
            node.value
            for node in scoped_nodes
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        ]
        sql_selects = [
            literal.lower()
            for literal in string_literals
            if "select" in literal.lower() and "tickets" in literal.lower()
        ]
        if any(token in function.name.lower() for token in ("ticket", "status")) and sql_selects:
            mentions_owner = any("owner_id" in literal for literal in string_literals) or any(
                isinstance(node, ast.Attribute) and node.attr == "owner_id" for node in scoped_nodes
            )
            if not mentions_owner:
                flags.add(f"ownership:ticket_read_may_not_filter_owner:{function.name}")
            is_ticket_read = any(
                token in function.name.lower() for token in ("get_ticket", "retrieve_ticket")
            )
            references_user_id = any(
                (isinstance(node, ast.Name) and node.id == "user_id")
                or (isinstance(node, ast.Attribute) and node.attr == "user_id")
                or (isinstance(node, ast.Constant) and node.value == "user_id")
                for node in scoped_nodes
            )
            if is_ticket_read and not references_user_id:
                flags.add(f"authentication:ticket_read_may_not_require_session:{function.name}")

        returns_json_response = any(
            isinstance(node, ast.Return)
            and isinstance(node.value, ast.Call)
            and (_dotted_name(node.value.func) or "").endswith("JSONResponse")
            for node in scoped_nodes
        )
        calls_cookie_setter = any(
            (_dotted_name(node.func) or "") in setter_functions for node in calls
        )
        if returns_json_response and (calls_cookie_setter or function.name in setter_functions):
            flags.add(f"session_cookie:verify_returned_response:{function.name}")
        if _is_session_route(function):
            writes_session_state = any(_writes_session_user_id(node) for node in scoped_nodes)
            sets_cookie = calls_cookie_setter or any(
                (_dotted_name(node.func) or "").rsplit(".", 1)[-1] == "set_cookie" for node in calls
            )
            if sets_cookie and not writes_session_state:
                flags.add(f"session_observer:verify_start_session_after_state:{function.name}")

        normalized_strings = [" ".join(value.lower().split()) for value in string_literals]
        updates_ticket_status = any(
            "update tickets" in literal and "set status" in literal
            for literal in normalized_strings
        )
        if updates_ticket_status:
            guard_tests = [
                node.test for node in scoped_nodes if isinstance(node, (ast.If, ast.IfExp))
            ]
            has_current_state_guard = any(
                any(_is_current_status_reference(candidate) for candidate in ast.walk(test))
                and any(_is_requested_status_reference(candidate) for candidate in ast.walk(test))
                for test in guard_tests
            )
            if not has_current_state_guard:
                flags.add(f"status_transition:verify_current_state_guard:{function.name}")

            owner_is_filtered_in_sql = any(
                "where" in literal and "owner_id" in literal.split("where", 1)[1]
                for literal in normalized_strings
            )
            owner_is_checked_in_branch = any(
                any(
                    (
                        isinstance(candidate, ast.Subscript)
                        and isinstance(candidate.slice, ast.Constant)
                        and candidate.slice.value == "owner_id"
                    )
                    or (isinstance(candidate, ast.Attribute) and candidate.attr == "owner_id")
                    for candidate in ast.walk(test)
                )
                and any(
                    (isinstance(candidate, ast.Name) and candidate.id == "user_id")
                    or (isinstance(candidate, ast.Attribute) and candidate.attr == "user_id")
                    for candidate in ast.walk(test)
                )
                for test in guard_tests
            )
            if not owner_is_filtered_in_sql and not owner_is_checked_in_branch:
                flags.add(f"ownership:verify_status_update_owner:{function.name}")

        if function.name == "create_app" and observer_middleware_reads_session_before_next:
            session_registration_lines = [
                node.lineno for node in calls if _is_session_middleware_registration(node)
            ]
            observer_registration_lines = [
                node.lineno for node in calls if _registered_session_observer(node)
            ]
            if any(
                session_line < observer_line
                for session_line in session_registration_lines
                for observer_line in observer_registration_lines
            ):
                flags.add("middleware_order:review_session_observer_registration:create_app")

    return sorted(imports), sorted(flags)


def inspect_proposals(
    project_root: str | Path,
    *,
    proposals_directory: str | Path = DEFAULT_PROPOSALS,
    output_path: str | Path = DEFAULT_STATIC_REPORT,
) -> dict[str, Any]:
    """Inspect proposal metadata and syntax only; never import or execute candidate code."""
    root = Path(project_root).resolve()
    proposal_root = Path(proposals_directory)
    if not proposal_root.is_absolute():
        proposal_root = root / proposal_root
    output = Path(output_path)
    if not output.is_absolute():
        output = root / output

    results: dict[str, dict[str, Any]] = {}
    for condition in CONDITIONS:
        proposal_path = proposal_root / f"{condition}.json"
        if not proposal_path.is_file():
            results[condition] = {"status": "missing_proposal"}
            continue
        try:
            proposal = ReconstructionProposal.model_validate_json(
                proposal_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            results[condition] = {
                "status": "invalid_proposal",
                "error": str(error)[:500],
            }
            continue

        code = proposal.proposed_code
        if proposal.condition != condition:
            results[condition] = {"status": "condition_mismatch"}
            continue
        if not proposal.requires_human_review:
            results[condition] = {"status": "review_flag_missing"}
            continue
        if not code or not code.strip():
            results[condition] = {"status": "no_code_generated"}
            continue

        candidate_digest = _sha256(code.encode("utf-8"))
        metadata = {
            "provider": proposal.provider,
            "provider_attempts": proposal.provider_attempts,
            "derivation": proposal.derivation.model_dump(mode="json")
            if proposal.derivation
            else None,
            "model": proposal.model,
            "request_id": proposal.request_id,
            "prompt_sha256": proposal.prompt_sha256,
            "candidate_sha256": candidate_digest,
            "usage": proposal.usage,
            "line_count": len(code.splitlines()),
            "requires_human_review": proposal.requires_human_review,
        }
        try:
            tree = ast.parse(code)
        except SyntaxError as error:
            results[condition] = {
                **metadata,
                "status": "syntax_error",
                "syntax_error": {
                    "line": error.lineno,
                    "message": error.msg,
                },
                "code_executed": False,
            }
            continue

        imports, review_flags = _static_findings(tree)
        findings: dict[str, Any] = {
            **metadata,
            "imports": imports,
            "manual_review_flags": review_flags,
            "code_executed": False,
        }
        if not proposal.prompt_sha256:
            results[condition] = {**findings, "status": "prompt_hash_missing"}
            continue
        try:
            expected_digest = _expected_prompt_sha256(root, condition)
        except (OSError, ValueError) as error:
            results[condition] = {
                **findings,
                "status": "prompt_context_unavailable",
                "error": str(error)[:500],
            }
            continue

        findings["expected_prompt_sha256"] = expected_digest
        findings["prompt_current"] = proposal.prompt_sha256 == expected_digest
        if not findings["prompt_current"]:
            findings["status"] = "stale_prompt"
        elif review_flags:
            findings["status"] = "manual_review_required"
        else:
            findings["status"] = "static_checks_passed"
        results[condition] = findings

    complete = all(
        results[condition].get("status") in {"static_checks_passed", "manual_review_required"}
        for condition in CONDITIONS
    )
    report_status = "incomplete"
    if complete:
        report_status = (
            "manual_review_required"
            if any(
                results[condition].get("status") == "manual_review_required"
                for condition in CONDITIONS
            )
            else "static_checks_passed"
        )
    report = {
        "static_review_schema_version": "1.1",
        "mode": "static_only",
        "status": report_status,
        "conditions": results,
        "candidate_code_executed": False,
        "manual_review_required": True,
        "functional_evaluation": "not_run",
        "security_assurance": "none",
        "limitations": [
            "AST parsing checks syntax and selected patterns only; it cannot establish safety.",
            "Manual review and isolated functional evaluation are still required.",
        ],
        "report_path": output.relative_to(root).as_posix()
        if output.is_relative_to(root)
        else str(output),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return report
