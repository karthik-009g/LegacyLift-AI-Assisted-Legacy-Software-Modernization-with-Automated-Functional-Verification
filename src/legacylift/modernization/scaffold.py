"""Versioned controller-owned setup for assembled migration candidates."""

import ast
import builtins
import dis
import inspect
import json
from importlib.resources import files
from types import CodeType

from .contracts import canonical_hash

CREATE_SCAFFOLD_V1 = """\
# LegacyLift controller scaffold: fastapi-create-v1
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import create_engine, text

app = FastAPI()
engine = create_engine(os.environ["DATABASE_URL"])


def first(db, sql, **params):
    return db.execute(text(sql), params).mappings().first()


def rows(db, sql, **params):
    return db.execute(text(sql), params).mappings().all()


def clock_now():
    epoch = int(Path("/state/clock").read_text(encoding="utf-8"))
    return datetime.fromtimestamp(epoch, timezone.utc)


# Model-authored migration begins below.
"""

CREATE_SCAFFOLD_V2 = (
    CREATE_SCAFFOLD_V1[: CREATE_SCAFFOLD_V1.index("def first(")].replace(
        "fastapi-create-v1", "fastapi-create-v2", 1
    )
    + """\
def _query(db, sql, params, named, fetch):
    statement = text(sql) if isinstance(sql, str) else sql
    bindings = {**(params or {}), **named}
    if db is engine:
        with engine.connect() as conn:
            return fetch(conn.execute(statement, bindings).mappings())
    return fetch(db.execute(statement, bindings).mappings())


def first(db, sql, params=None, **named):
    return _query(db, sql, params, named, lambda result: result.first())


def rows(db, sql, params=None, **named):
    return _query(db, sql, params, named, lambda result: result.all())


"""
    + CREATE_SCAFFOLD_V1[CREATE_SCAFFOLD_V1.index("def clock_now(") :]
)
CREATE_SCAFFOLD_V3 = (
    CREATE_SCAFFOLD_V2[: CREATE_SCAFFOLD_V2.index("def clock_now(")].replace(
        "fastapi-create-v2", "fastapi-create-v3", 1
    )
    + """\
def project_permissions(db, user_id, project_id):
    roles = rows(
        db,
        'SELECT r.permissions FROM members m '
        'JOIN member_roles mr ON mr.member_id = m.id '
        'JOIN roles r ON r.id = mr.role_id '
        'WHERE m.user_id = :user_id AND m.project_id = :project_id',
        user_id=user_id,
        project_id=project_id,
    )
    permissions = set()
    for role in roles:
        for entry in (role['permissions'] or '').splitlines():
            prefix, separator, name = entry.strip().partition('- :')
            if not prefix and separator and name.strip():
                permissions.add(name.strip())
    return frozenset(permissions)


"""
    + CREATE_SCAFFOLD_V2[CREATE_SCAFFOLD_V2.index("def clock_now(") :]
)
CREATE_SCAFFOLD_VERSION = "fastapi-create-v4"
CREATE_SCAFFOLD = """\
# LegacyLift controller scaffold: fastapi-create-v4
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from sqlalchemy import create_engine, text

app = FastAPI()
_engine = create_engine(os.environ["DATABASE_URL"])


def _read(sql, params, conn, fetch):
    if conn is not None:
        return fetch(conn.execute(text(sql), params or {}).mappings())
    with _engine.connect() as opened:
        return fetch(opened.execute(text(sql), params or {}).mappings())


def read_one(sql, params=None, *, conn=None):
    return _read(sql, params, conn, lambda result: result.first())


def read_many(sql, params=None, *, conn=None):
    return _read(sql, params, conn, lambda result: result.all())


def transaction():
    return _engine.begin()


def write(conn, sql, params=None):
    return conn.execute(text(sql), params or {}).lastrowid


def project_permissions(user_id, project_id):
    roles = read_many(
        'SELECT r.permissions FROM members m '
        'JOIN member_roles mr ON mr.member_id = m.id '
        'JOIN roles r ON r.id = mr.role_id '
        'WHERE m.user_id = :user_id AND m.project_id = :project_id',
        {'user_id': user_id, 'project_id': project_id},
    )
    permissions = set()
    for role in roles:
        for entry in (role['permissions'] or '').splitlines():
            prefix, separator, name = entry.strip().partition('- :')
            if not prefix and separator and name.strip():
                permissions.add(name.strip())
    return frozenset(permissions)


def clock_now():
    epoch = int(Path("/state/clock").read_text(encoding="utf-8"))
    return datetime.fromtimestamp(epoch, timezone.utc)


@app.post("/issues.json")
async def _create_endpoint(request: Request):
    try:
        payload = await request.json()
    except ValueError:
        payload = None
    return await run_in_threadpool(
        create_issue, request.headers.get("X-Redmine-API-Key"), payload, str(request.base_url)
    )


# Model-authored migration begins below.
"""
READ_SCAFFOLD_VERSION = "fastapi-read-v3"
READ_SCAFFOLD_V1 = (
    CREATE_SCAFFOLD[: CREATE_SCAFFOLD.index('@app.post("/issues.json")')].replace(
        CREATE_SCAFFOLD_VERSION, "fastapi-read-v1", 1
    )
    + """\
def actor_for_key(api_key):
    if not api_key:
        return None
    return read_one(
        "SELECT u.* FROM tokens t JOIN users u ON u.id = t.user_id "
        "WHERE t.action = 'api' AND t.value = :key",
        {'key': api_key},
    )


async def _issue_payload(request):
    try:
        return await request.json()
    except ValueError:
        return None


@app.get("/issues/{issue_id}.json")
async def _read_endpoint(issue_id: int, request: Request):
    return await run_in_threadpool(
        read_issue, request.headers.get("X-Redmine-API-Key"), issue_id,
        request.query_params.get("include"),
    )


@app.post("/issues.json")
async def _create_endpoint(request: Request):
    return await run_in_threadpool(
        create_issue, request.headers.get("X-Redmine-API-Key"), await _issue_payload(request),
        str(request.base_url),
    )


@app.put("/issues/{issue_id}.json")
async def _update_endpoint(issue_id: int, request: Request):
    return await run_in_threadpool(
        update_issue, request.headers.get("X-Redmine-API-Key"), issue_id,
        await _issue_payload(request),
    )


# Model-authored migration begins below.
"""
)
READ_SCAFFOLD_V2 = (
    READ_SCAFFOLD_V1.replace("fastapi-read-v1", "fastapi-read-v2", 1)
    .replace(
        "        return await request.json()\n",
        "        document = await request.json()\n"
        "        issue = document.get('issue') if isinstance(document, dict) else None\n"
        "        return issue if isinstance(issue, dict) else None\n",
        1,
    )
    .replace(
        '@app.get("/issues/{issue_id}.json")',
        """\
def iso_utc(value):
    if value is None:
        return None
    timestamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


@app.get("/issues/{issue_id}.json")""",
        1,
    )
)
READ_SCAFFOLD = READ_SCAFFOLD_V2.replace("fastapi-read-v2", READ_SCAFFOLD_VERSION, 1).replace(
    'request.query_params.get("include"),',
    'request.query_params.get("include", ""),',
    1,
)
READ_COMPOSED_SCAFFOLD_VERSION = "fastapi-read-v4-reviewed-update"
REVIEWED_UPDATE_BINDING = {
    "workflow": "update",
    "run_id": "664dedffc38744058e786f61c65d0f25",
    "source_sha256": "d81331cc44c4a2bd59deb29fc6338bbcb03442ec37220f8ef92da722d8a18abc",
    "reviewer": "goku",
    "license_file": "redmine-COPYING.txt",
}


def _compose_reviewed_update() -> str:
    source = (
        files("legacylift.runtimes")
        .joinpath("assets/reviewed_update.py.txt")
        .read_text(encoding="utf-8")
    )
    if canonical_hash(source) != REVIEWED_UPDATE_BINDING["source_sha256"]:
        raise ValueError("reviewed update asset differs from its approved source")
    factory = (
        "# Supporting update from reviewed run " + REVIEWED_UPDATE_BINDING["run_id"] + ".\n"
        "# Derived Redmine logic retains upstream licensing. See packaged redmine-COPYING.txt.\n"
        "def _reviewed_update_factory():\n"
        + "".join(
            "    " + line if line.strip() else line for line in source.splitlines(keepends=True)
        )
        + "\n    return update_issue\n\n"
        "_reviewed_update_handler = _reviewed_update_factory()\n\n"
    )
    old_route = (
        "    return await run_in_threadpool(\n"
        '        update_issue, request.headers.get("X-Redmine-API-Key"), issue_id,\n'
        "        await _issue_payload(request),\n"
        "    )"
    )
    if READ_SCAFFOLD.count(old_route) != 1:
        raise ValueError("reviewed update route binding is ambiguous")
    return (
        READ_SCAFFOLD.replace(READ_SCAFFOLD_VERSION, READ_COMPOSED_SCAFFOLD_VERSION, 1)
        .replace(old_route, "    return await _reviewed_update_handler(issue_id, request)", 1)
        .replace(
            "# Model-authored migration begins below.",
            factory + "# Model-authored migration begins below.",
            1,
        )
    )


READ_COMPOSED_SCAFFOLD = _compose_reviewed_update()
CREATE_SCAFFOLDS = {
    "fastapi-create-v1": CREATE_SCAFFOLD_V1,
    "fastapi-create-v2": CREATE_SCAFFOLD_V2,
    "fastapi-create-v3": CREATE_SCAFFOLD_V3,
    CREATE_SCAFFOLD_VERSION: CREATE_SCAFFOLD,
}
READ_SCAFFOLDS = {
    "fastapi-read-v1": READ_SCAFFOLD_V1,
    "fastapi-read-v2": READ_SCAFFOLD_V2,
    READ_SCAFFOLD_VERSION: READ_SCAFFOLD,
    READ_COMPOSED_SCAFFOLD_VERSION: READ_COMPOSED_SCAFFOLD,
}
_SCAFFOLDS = {**CREATE_SCAFFOLDS, **READ_SCAFFOLDS}


def scaffold_api(version: str) -> str:
    if version == READ_COMPOSED_SCAFFOLD_VERSION:
        return (
            scaffold_api(READ_SCAFFOLD_VERSION)
            .replace(", update_issue(api_key,issue_id,payload)", "")
            .replace("POST/PUT payload", "POST payload")
            + "PUT is supplied by the reviewed update implementation. Define read/create only. "
        )
    if version in READ_SCAFFOLDS:
        payload_contract = (
            "POST/PUT payload is the inner issue dict, or None if missing/malformed. "
            "Use payload fields directly. iso_utc(value) formats SQLite timestamps or "
            "datetimes as UTC/Z, preserving None. "
            if version in {"fastapi-read-v2", READ_SCAFFOLD_VERSION}
            else "The controller registers GET/POST/PUT and passes parsed JSON or None. "
        )
        return (
            "Define synchronous read_issue(api_key,issue_id,include), "
            "create_issue(api_key,payload,base_url), update_issue(api_key,issue_id,payload). "
            f"{payload_contract}"
            + (
                "include is a string, empty when omitted. "
                if version == READ_SCAFFOLD_VERSION
                else ""
            )
            + "No Request "
            "object. actor_for_key(api_key) returns the original users mapping or None, using "
            "tokens.value and action='api'. Use it, then enforce actor validity, visibility and "
            "route permissions in your handlers. project_permissions(user_id,project_id) gives "
            "a frozenset for explicit memberships. read_one(sql,params,*,conn=None) returns "
            "a string-keyed mapping or None; read_many returns a list. SQL :name binds take a "
            "dict. Use with transaction() as conn and write(conn,sql,params); write returns the "
            "inserted id. Only reads take conn=. clock_now() provides UTC fixture time. "
            "base_url ends in '/'; strip it before appending the Location path. Return Response "
            "or JSONResponse, both supplied. Do not import FastAPI, redefine supplied helpers, "
            "register routes, call execute or open another engine. "
        )
    if version == CREATE_SCAFFOLD_VERSION:
        return (
            "Define def create_issue(api_key, payload, base_url): returning Response or "
            "JSONResponse. The scaffold routes POST, reads the optional API key and parses JSON "
            "(None if malformed). No Request object is supplied; do not use a request variable. "
            "base_url is a string ending in '/'; use base_url.rstrip('/') before appending "
            "'/issues/{id}' for Location. Write synchronous code only. "
            "Use named SQL binds and a dict: read_one('SELECT id FROM users WHERE id=:id', "
            "{'id': value}) returns a string-keyed mapping or None; access row['id'], never "
            "row[0]. read_many(sql,params) returns a list of mappings. Never pass '?' SQL "
            "placeholders, tuples or lists as parameters; "
            "pass conn=conn to read inside a transaction. Use with transaction() as conn and "
            "write(conn,sql,params), which returns the inserted row id. "
            "Only read helpers accept conn=; write receives its connection positionally. "
            "project_permissions(user_id,project_id) returns frozenset[str], never a dict. "
            "clock_now() supplies UTC fixture time. Use these helpers without registering routes, "
            "opening your own engine, or calling execute directly. "
        )
    query_contract = (
        "Use first(conn,sql,**params) or rows(conn,sql,**params) with a connection. "
        if version == "fastapi-create-v1"
        else "Use first(engine,sql,params) or rows(engine,sql,params). Pass a connection to "
        "read inside its transaction. "
    )
    permissions = (
        "project_permissions(db,user_id,project_id) returns exact permission names for "
        "explicit project memberships. "
        if version == "fastapi-create-v3"
        else ""
    )
    return (
        f"The controller prepends {version} with app, Request, JSONResponse, Response, "
        f"engine, text, and clock_now() (UTC fixture time). {query_contract}"
        f"{permissions}Use engine.begin() for writes. Keep the provided setup unchanged. "
    )


def create_scaffold_binding(version: str = CREATE_SCAFFOLD_VERSION) -> dict:
    binding = {
        "version": version,
        "scaffold_sha256": canonical_hash(_SCAFFOLDS[version]),
    }
    if version == READ_COMPOSED_SCAFFOLD_VERSION:
        binding["supporting_implementations"] = [dict(REVIEWED_UPDATE_BINDING)]
    return binding


def candidate_scaffold(context: dict) -> str:
    binding = context.get("source_assembly")
    if binding is None:
        return ""
    version = binding.get("version") if isinstance(binding, dict) else None
    if (
        not isinstance(version, str)
        or version not in _SCAFFOLDS
        or context.get("workflow") != ("read" if version in READ_SCAFFOLDS else "create")
        or context.get("condition") != "hybrid"
        or binding != create_scaffold_binding(version)
    ):
        raise ValueError("candidate scaffold does not match the saved generation context")
    return _SCAFFOLDS[version]


def model_fragment(source: str, scaffold: str) -> str:
    if not source.startswith(scaffold):
        raise ValueError("candidate changed controller-owned scaffold")
    return source[len(scaffold) :]


def fragment_is_evidence_echo(fragment: str) -> bool:
    text = fragment.strip().rstrip(",")
    if text.startswith('"'):
        # An array of quoted excerpts may arrive as bare string statements. It can
        # parse and boot as Python even though it registers no route.
        try:
            return all(
                isinstance(json.loads(line), str) for line in text.splitlines() if line.strip()
            )
        except (ValueError, RecursionError):
            return False
    if not text.startswith("{"):
        return False
    try:
        objects = json.loads(f"[{text}]")
    except (ValueError, RecursionError):
        return False
    return bool(objects) and all(
        isinstance(item, dict) and isinstance(item.get("evidence_id"), str) for item in objects
    )


def create_interface_findings(scaffold: str, fragment: str) -> list[dict]:
    read_scaffold = scaffold in READ_SCAFFOLDS.values()
    if scaffold != CREATE_SCAFFOLD and not read_scaffold:
        return []
    prefix = "read" if read_scaffold else "create"
    required = (
        ("read_issue", "create_issue")
        if scaffold == READ_COMPOSED_SCAFFOLD
        else ("read_issue", "create_issue", "update_issue")
        if prefix == "read"
        else ("create_issue",)
    )
    try:
        tree = ast.parse(fragment)
    except SyntaxError:
        # Full review resolves syntax against the target Python version.
        return []
    offset = scaffold.count("\n")
    for name in required:
        functions = [
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        ]
        line = offset + (functions[0].lineno if functions else 1)
        finding = {"rule": f"{prefix}_handler_signature", "severity": "error", "line": line}
        if (
            len(functions) != 1
            or not isinstance(functions[0], ast.FunctionDef)
            or functions[0].decorator_list
        ):
            return [{**finding, "message": f"Define one undecorated synchronous {name} function."}]
        try:
            _ast_signature(functions[0].args).bind(None, None, None)
        except TypeError as error:
            return [{**finding, "message": f"{name}: {error}"}]
    findings = [
        {"rule": f"{prefix}_handler_integration", "severity": "error", "line": offset + node.lineno}
        for node in ast.walk(tree)
        if isinstance(node, (ast.AsyncWith, ast.Await))
        or (isinstance(node, ast.Name) and node.id in {"app", "engine", "_engine", "create_engine"})
        or (isinstance(node, ast.Attribute) and node.attr == "execute")
    ]
    helpers = {
        node.name: _ast_signature(node.args)
        for node in ast.parse(scaffold).body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }
    if read_scaffold:
        local_response_imports = set()
        for function in tree.body:
            if not isinstance(function, ast.FunctionDef) or function.name not in required:
                continue
            for statement in function.body:
                if not isinstance(statement, (ast.Import, ast.ImportFrom)):
                    break
                if (
                    isinstance(statement, ast.ImportFrom)
                    and statement.module == "fastapi.responses"
                    and all(
                        alias.name in {"Response", "JSONResponse"}
                        and alias.asname in {None, alias.name}
                        for alias in statement.names
                    )
                ):
                    local_response_imports.add(statement)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in helpers:
                message = f"Use the supplied {node.name} helper without redefining it."
            elif (
                isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "fastapi"
            ):
                if node in local_response_imports:
                    continue
                message = "Remove FastAPI imports. Response and JSONResponse are supplied."
            elif isinstance(node, ast.Import) and any(
                item.name.split(".")[0] == "fastapi" for item in node.names
            ):
                message = "Use the scaffold's Response and JSONResponse without importing FastAPI."
            else:
                continue
            findings.append(
                {
                    "rule": "read_scaffold_override",
                    "severity": "error",
                    "line": offset + node.lineno,
                    "message": message,
                }
            )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        if (
            node.func.id in helpers
            and not any(isinstance(arg, ast.Starred) for arg in node.args)
            and all(k.arg for k in node.keywords)
        ):
            try:
                helpers[node.func.id].bind(
                    *[None for _ in node.args], **{key.arg: None for key in node.keywords}
                )
            except TypeError as error:
                findings.append(
                    {
                        "rule": f"{prefix}_helper_signature",
                        "severity": "error",
                        "line": offset + node.lineno,
                        "message": f"{node.func.id}: {error}",
                    }
                )
        parameter_index = {"read_one": 1, "read_many": 1, "write": 2}.get(node.func.id)
        if parameter_index is None:
            continue
        params = next((item.value for item in node.keywords if item.arg == "params"), None)
        if len(node.args) > parameter_index:
            params = node.args[parameter_index]
        if isinstance(params, (ast.Tuple, ast.List)):
            findings.append(
                {
                    "rule": f"{prefix}_helper_parameters",
                    "severity": "error",
                    "line": offset + node.lineno,
                    "message": "Use SQL :name binds and a parameter dict, not positional values. "
                    "Read helpers return mappings: access row['id'], not row[0].",
                }
            )
    for node in ast.walk(tree):
        if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not isinstance(call.func, ast.Name) or call.func.id != "JSONResponse":
            continue
        values = {
            key.arg: key.value.value for key in call.keywords if isinstance(key.value, ast.Constant)
        }
        content = values.get("content", object())
        if call.args and isinstance(call.args[0], ast.Constant):
            content = call.args[0].value
        if values.get("status_code") in {401, 403, 404} and content is None:
            findings.append(
                {
                    "rule": f"{prefix}_bodyless_response",
                    "severity": "error",
                    "line": offset + node.lineno,
                    "message": "JSONResponse(None) writes a null body. Return Response "
                    "with the same status/headers for this bodyless response contract.",
                }
            )
    findings.extend(_undefined_fragment_globals(scaffold + fragment, offset, prefix))
    return findings


def _ast_signature(arguments: ast.arguments) -> inspect.Signature:
    """Read call arity/default presence without evaluating annotations or default expressions."""
    positional = [*arguments.posonlyargs, *arguments.args]
    required = len(positional) - len(arguments.defaults)
    parameters = [
        inspect.Parameter(
            arg.arg,
            inspect.Parameter.POSITIONAL_ONLY
            if i < len(arguments.posonlyargs)
            else inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=inspect.Parameter.empty if i < required else None,
        )
        for i, arg in enumerate(positional)
    ]
    if arguments.vararg:
        parameters.append(inspect.Parameter(arguments.vararg.arg, inspect.Parameter.VAR_POSITIONAL))
    parameters.extend(
        inspect.Parameter(
            arg.arg,
            inspect.Parameter.KEYWORD_ONLY,
            default=inspect.Parameter.empty if default is None else None,
        )
        for arg, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
    )
    if arguments.kwarg:
        parameters.append(inspect.Parameter(arguments.kwarg.arg, inspect.Parameter.VAR_KEYWORD))
    return inspect.Signature(parameters)


def _undefined_fragment_globals(source: str, offset: int, prefix: str) -> list[dict]:
    """Inspect compiled instructions as data; never evaluate or execute candidate code."""
    try:
        module = compile(source, "<candidate-preflight>", "exec")
    except SyntaxError:
        return []  # The target interpreter remains authoritative for Python 3.14 grammar.
    definitions = {i.argval for i in dis.get_instructions(module) if i.opname == "STORE_NAME"}
    known = (
        set(vars(builtins))
        | definitions
        | {
            "__name__",
            "__file__",
            "__package__",
            "__spec__",
            "__builtins__",
            "app",
            "engine",
            "_engine",
            "create_engine",  # Already checked by the integration rule.
        }
    )
    scopes = [module]
    for scope in scopes:
        scopes.extend(item for item in scope.co_consts if isinstance(item, CodeType))
        known.update(i.argval for i in dis.get_instructions(scope) if i.opname == "STORE_GLOBAL")
    findings, seen = [], set()
    for scope in scopes:
        for instruction in dis.get_instructions(scope):
            line = instruction.positions.lineno or scope.co_firstlineno
            name = instruction.argval
            if (
                instruction.opname == "LOAD_GLOBAL"
                and line > offset
                and name not in known
                and name not in seen
            ):
                findings.append(
                    {
                        "rule": f"{prefix}_undefined_global",
                        "severity": "error",
                        "line": line,
                        "message": f"Undefined name {name!r}; use supplied parameters/helpers.",
                    }
                )
                seen.add(name)
    return findings


def source_assembly_metadata(scaffold: str, fragment: str) -> dict:
    version = next((name for name, code in _SCAFFOLDS.items() if code == scaffold), None)
    if version is None:
        raise ValueError("unknown controller scaffold")
    return {
        **create_scaffold_binding(version),
        "fragment_sha256": canonical_hash(fragment),
        "model_first_line": scaffold.count("\n") + 1,
        "authorship": "controller_scaffold_plus_model_fragment",
    }
