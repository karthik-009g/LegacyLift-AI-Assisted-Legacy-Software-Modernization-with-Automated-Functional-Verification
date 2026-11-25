"""Transparent static review; a passed review is not a security certification."""

import ast
import sys

BLOCKED_MODULES = {
    "subprocess",
    "socket",
    "httpx",
    "requests",
    "urllib",
    "ctypes",
    "pickle",
    "marshal",
    "importlib",
    "shutil",
    "multiprocessing",
}
BLOCKED_CALLS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "breakpoint",
    "system",
    "popen",
    "fork",
    "spawn",
    "unlink",
    "remove",
    "rmdir",
    "rmtree",
    "chmod",
    "chown",
}
ALLOWED_EXTERNAL_IMPORTS = {"fastapi", "sqlalchemy"}
BODYLESS_HTTP_ERROR_STATUSES = {401, 403, 404}
STATIC_POLICY_VERSION = "2.4-capability-references"


def _call_name(function) -> str:
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return ""


def _literal_clock_path(expression, constant_names: set[str]) -> bool:
    if isinstance(expression, ast.Name) and expression.id in constant_names:
        return True
    if not isinstance(expression, ast.Call) or _call_name(expression.func) != "Path":
        return False
    if not expression.args:
        return False
    value = expression.args[0]
    return (isinstance(value, ast.Constant) and value.value == "/state/clock") or (
        isinstance(value, ast.Name) and value.id in constant_names
    )


def review_source(source: str) -> dict:
    findings = []
    if not source.strip():
        return {
            "status": "blocked",
            "findings": [{"rule": "empty_source", "line": 1}],
            "reviewer": "automated_ast_policy",
            "policy_version": STATIC_POLICY_VERSION,
            "certified_secure": False,
        }
    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return {
            "status": "blocked",
            "findings": [
                {
                    "rule": "invalid_python",
                    "line": error.lineno,
                    "offset": error.offset,
                    "message": error.msg,
                }
            ],
            "certified_secure": False,
            "policy_version": STATIC_POLICY_VERSION,
        }
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    http_handler_registered = False
    for statement in tree.body:
        registrations = (
            statement.decorator_list
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            else [statement.value]
            if isinstance(statement, ast.Expr)
            else []
        )
        for registration in registrations:
            if (
                isinstance(registration, ast.Call)
                and isinstance(registration.func, ast.Attribute)
                and isinstance(registration.func.value, ast.Name)
                and registration.func.value.id == "app"
                and registration.func.attr in {"exception_handler", "add_exception_handler"}
                and registration.args
                and _call_name(registration.args[0]) == "HTTPException"
            ):
                http_handler_registered = True
    scope_types = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)

    def scope_for(node):
        current = parents.get(node)
        while current is not None and current is not tree:
            if isinstance(current, scope_types):
                return current
            current = parents.get(current)
        return tree

    def scope_chain(scope):
        current = scope
        while current is not tree:
            yield current
            parent = parents.get(current)
            while parent is not None and parent is not tree and not isinstance(parent, scope_types):
                parent = parents.get(parent)
            # A method does not resolve a bare name through its class namespace.
            if isinstance(parent, ast.ClassDef) and isinstance(
                current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
            ):
                parent = parents.get(parent)
                while (
                    parent is not None
                    and parent is not tree
                    and not isinstance(parent, scope_types)
                ):
                    parent = parents.get(parent)
            current = parent or tree
        yield tree

    def assigned_names(target):
        if isinstance(target, ast.Name):
            return {target.id}
        if isinstance(target, (ast.Tuple, ast.List)):
            return set().union(*(assigned_names(item) for item in target.elts))
        return set()

    path_names_by_scope: dict[ast.AST, set[str]] = {tree: set()}
    assignments = [node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))]
    for node in assignments:
        value = node.value
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if isinstance(value, ast.Constant) and value.value == "/state/clock":
            path_names_by_scope.setdefault(scope_for(node), set()).update(
                set().union(*(assigned_names(target) for target in targets))
            )

    def scoped_path_names(scope):
        return set().union(*(path_names_by_scope.get(item, set()) for item in scope_chain(scope)))

    changed = True
    while changed:
        changed = False
        for node in assignments:
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            scope = scope_for(node)
            names = set().union(*(assigned_names(target) for target in targets))
            if names and _literal_clock_path(value, scoped_path_names(scope)):
                existing = path_names_by_scope.setdefault(scope, set())
                before = len(existing)
                existing.update(names)
                changed |= len(existing) != before

    app_is_bound = False
    for node in tree.body:
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, ast.AnnAssign)
            else []
        )
        app_is_bound |= any(
            isinstance(target, ast.Name) and target.id == "app" for target in targets
        )
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
    clock_read = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(node.ctx, ast.Load):
            name = node.id if isinstance(node, ast.Name) else node.attr
            parent = parents.get(node)
            directly_called = isinstance(parent, ast.Call) and parent.func is node
            if name in BLOCKED_CALLS and not directly_called:
                findings.append(
                    {"rule": "prohibited_capability_reference", "name": name, "line": node.lineno}
                )
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                modules = [alias.name.split(".")[0] for alias in node.names]
            else:
                modules = [(node.module or "").split(".")[0]]
            for module in set(modules) & BLOCKED_MODULES:
                findings.append(
                    {"rule": "prohibited_capability", "name": module, "line": node.lineno}
                )
            for module in set(modules):
                if (
                    module
                    and module not in sys.stdlib_module_names
                    and module not in ALLOWED_EXTERNAL_IMPORTS
                ):
                    findings.append(
                        {"rule": "unsupported_dependency", "name": module, "line": node.lineno}
                    )
            if isinstance(node, ast.ImportFrom) and node.level:
                findings.append({"rule": "relative_import_not_supported", "line": node.lineno})
            if isinstance(node, ast.ImportFrom):
                for name in {alias.name for alias in node.names} & BLOCKED_CALLS:
                    findings.append(
                        {
                            "rule": "prohibited_capability_reference",
                            "name": name,
                            "line": node.lineno,
                        }
                    )
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            function = node.exc.func
            if _call_name(function) == "HTTPException":
                status = next(
                    (
                        keyword.value
                        for keyword in node.exc.keywords
                        if keyword.arg == "status_code"
                    ),
                    node.exc.args[0] if node.exc.args else None,
                )
                if (
                    isinstance(status, ast.Constant)
                    and status.value in BODYLESS_HTTP_ERROR_STATUSES
                    and not http_handler_registered
                ):
                    findings.append(
                        {
                            "rule": "default_http_exception_body",
                            "line": node.lineno,
                            "severity": "warning",
                            "category": "compatibility",
                            "message": "HTTPException may emit a JSON error body; "
                            "independent replay must verify the reference response contract.",
                        }
                    )
        if isinstance(node, ast.Call):
            function = node.func
            path_names = scoped_path_names(scope_for(node))
            if (
                isinstance(function, ast.Attribute)
                and function.attr in {"read_text", "read_bytes"}
                and _literal_clock_path(function.value, path_names)
            ):
                clock_read = True
            elif (
                _call_name(function) == "open"
                and node.args
                and (
                    (
                        isinstance(node.args[0], ast.Constant)
                        and node.args[0].value == "/state/clock"
                    )
                    or (isinstance(node.args[0], ast.Name) and node.args[0].id in path_names)
                )
                and (
                    len(node.args) == 1
                    or (isinstance(node.args[1], ast.Constant) and node.args[1].value == "r")
                )
            ):
                clock_read = True
            name = _call_name(function)
            if name in BLOCKED_CALLS:
                findings.append({"rule": "prohibited_call", "name": name, "line": node.lineno})
            if (
                name == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
                and node.args[1].value in BLOCKED_CALLS
            ):
                findings.append(
                    {
                        "rule": "prohibited_capability_reference",
                        "name": node.args[1].value,
                        "line": node.lineno,
                    }
                )
    if not app_is_bound:
        findings.append({"rule": "missing_asgi_app", "line": 1})
    write_routes = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "app"
        and node.func.attr in {"post", "put", "patch", "delete"}
    ]
    if write_routes and not clock_read:
        findings.append({"rule": "fixture_clock_required", "line": min(write_routes)})
    return {
        "status": "blocked"
        if any(item.get("severity") != "warning" for item in findings)
        else "static_review_passed",
        "findings": findings,
        "reviewer": "automated_ast_policy",
        "policy_version": STATIC_POLICY_VERSION,
        "certified_secure": False,
        "compatibility_notes": (
            [
                "Custom HTTPException handler registration observed; its response semantics "
                "still require independent runtime verification."
            ]
            if http_handler_registered
            else []
        ),
        "limits": [
            "AST checks cannot prove application security or prevent all obfuscation.",
            "Only Python standard-library, FastAPI, and SQLAlchemy imports are allowed.",
            "Write routes must preserve the fixture clock and bodyless error response contract.",
            "Execution still requires the restricted, credential-free Docker runtime.",
        ],
    }


def review_target_source(source: str) -> dict:
    """Use target grammar for syntax/stdlib differences; never execute the candidate."""
    import subprocess
    from pathlib import Path

    from legacylift.runtimes.static_review import run_target_static_review

    host = review_source(source)
    rules = {item["rule"] for item in host.get("findings", []) if item.get("severity") != "warning"}
    if not rules or not rules <= {"invalid_python", "unsupported_dependency"}:
        return host
    try:
        return run_target_static_review(source, Path(__file__).read_bytes())
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        return {
            "status": "blocked",
            "certified_secure": False,
            "reviewer": "automated_ast_policy",
            "policy_version": STATIC_POLICY_VERSION,
            "findings": [
                {
                    "rule": "target_static_review_unavailable",
                    "line": 1,
                    "error_type": type(error).__name__,
                }
            ],
        }


def approval_review_passes(source: str, attempts: list[dict]) -> bool:
    """Approval APIs reuse a checksum-bound target review instead of needing Docker access."""
    import hashlib
    from pathlib import Path

    host = review_source(source)
    if host["status"] == "static_review_passed":
        return True
    if not {
        item["rule"] for item in host.get("findings", []) if item.get("severity") != "warning"
    } <= {
        "invalid_python",
        "unsupported_dependency",
    }:
        return False
    if not attempts:
        return False
    review = attempts[-1].get("review", {})
    return (
        review.get("status") == "static_review_passed"
        and review.get("parser_runtime") == "python-target-container"
        and str(review.get("parser_python_version", "")).startswith("3.14.")
        and review.get("policy_version") == STATIC_POLICY_VERSION
        and review.get("source_utf8_sha256") == hashlib.sha256(source.encode("utf-8")).hexdigest()
        and review.get("policy_sha256") == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    )
