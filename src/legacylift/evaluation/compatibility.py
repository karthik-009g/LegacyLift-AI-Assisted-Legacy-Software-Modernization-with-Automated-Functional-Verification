"""Reproducible, labeled harness repairs for the three saved study drafts.

This is a fixed experiment recipe, not a general code repair engine. It reads
candidate text only, rejects unexpected inputs, and never imports model code.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from legacylift.reconstruction.models import ProposalDerivation, ReconstructionProposal

RAW_CANDIDATE_HASHES = {
    "source_only": "e2de6df72fa7a286e25b7a5fe3a4499c1084a9264ae248b3188a0c8d557a53b8",
    "runtime_only": "37d8c95b9485c2ff7974f95017faaab0e912f15d38a13d11dd394c19d44deed6",
    "hybrid": "d70ddc88251cd76bf64bc9d26bf7629d598ac875fa47a8cba7b4387cea8ba7c2",
}


def _replace_once(code: str, old: str, new: str) -> str:
    if code.count(old) != 1:
        raise ValueError("compatibility recipe no longer matches the saved draft")
    return code.replace(old, new, 1)


def _repair(code: str, condition: str) -> tuple[str, list[str]]:
    changes = []
    if condition in {"source_only", "hybrid"}:
        code = _replace_once(
            code,
            "from fastapi.middleware.sessions import SessionMiddleware",
            "from starlette.middleware.sessions import SessionMiddleware",
        )
        changes.append("Import SessionMiddleware from its installed Starlette module.")
    if condition == "source_only":
        code = _replace_once(
            code,
            'str(Path(app.root_path) / "instance" / "legacylift.sqlite3")',
            'str(Path("instance") / "legacylift.sqlite3")',
        )
        changes.append("Remove Flask-only root_path access when constructing default config.")
        session_registration = (
            '    app.add_middleware(SessionMiddleware, secret_key=config["SECRET_KEY"], '
            'session_cookie="session")'
        )
        code = _replace_once(code, session_registration + "\n", "")
        code = re.sub(r"(?m)^ *observe_session\(request, before\)\n", "", code)
        observer = """    @app.middleware("http")
    async def observe_request_session(request: Request, call_next):
        before = {"user_id": request.session.get("user_id")}
        response = await call_next(request)
        observer = config.get("SESSION_OBSERVER")
        if observer and request.url.path.startswith(("/session", "/tickets")):
            observer({"before": before, "after": {"user_id": request.session.get("user_id")}})
        return response

"""
        code = _replace_once(code, "    # Utility to invoke", observer + "    # Utility to invoke")
        code = _replace_once(code, "    return app", session_registration + "\n\n    return app")
        changes.append(
            "Invoke the normalized session observer once per request, including validation errors, "
            "inside the session middleware. No route or business rule is corrected."
        )
    elif condition == "runtime_only":
        code = _replace_once(
            code,
            "async def start_session(req: SessionRequest, response: Response):",
            "async def start_session(req: SessionRequest, response: Response, request: Request):",
        )
        code = _replace_once(code, "request = Request.scope", "request.state.user_id = req.user_id")
        changes.append("Use the injected Request instance to update observer after-state.")
    elif condition == "hybrid":
        session_registration = (
            "    app.add_middleware(SessionMiddleware, secret_key=secret_key, "
            'session_cookie="session")'
        )
        observer_registration = '    app.middleware("http")(session_observer_middleware)'
        code = _replace_once(
            code,
            session_registration + "\n" + observer_registration,
            observer_registration + "\n" + session_registration,
        )
        changes.append(
            "Register session middleware outside the observer so request.session exists."
        )
    return code, changes


def prepare_compatibility_repairs(
    proposals_directory: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    """Validate every input before saving separate, deterministic repaired copies."""
    source = Path(proposals_directory).resolve()
    output = Path(output_directory).resolve()
    if source == output:
        raise ValueError("compatibility repairs must be saved separately from raw proposals")
    prepared = {}
    entries = {}
    for condition, expected_hash in RAW_CANDIDATE_HASHES.items():
        proposal = ReconstructionProposal.model_validate_json(
            (source / f"{condition}.json").read_text(encoding="utf-8")
        )
        original = proposal.proposed_code or ""
        digest = hashlib.sha256(original.encode("utf-8")).hexdigest()
        if proposal.condition != condition or digest != expected_hash or proposal.derivation:
            raise ValueError(f"{condition}: compatibility recipe requires the original saved draft")
        repaired, changes = _repair(original, condition)
        derivation = ProposalDerivation(
            kind="agent_compatibility_repair", parent_candidate_sha256=digest, changes=changes
        )
        prepared[condition] = proposal.model_copy(
            update={"proposed_code": repaired, "derivation": derivation}
        )
        entries[condition] = {
            **derivation.model_dump(mode="json"),
            "candidate_sha256": hashlib.sha256(repaired.encode("utf-8")).hexdigest(),
            "diff": "".join(
                difflib.unified_diff(
                    original.splitlines(keepends=True),
                    repaired.splitlines(keepends=True),
                    fromfile=f"raw/{condition}.py",
                    tofile=f"compatibility_repaired/{condition}.py",
                )
            ),
        }
    report = {
        "schema_version": "1.0",
        "candidate_code_executed": False,
        "scope": (
            "Fixed startup and evaluator callback repairs; business logic remains as generated."
        ),
        "conditions": entries,
        "human_correction_effort": {
            "status": "not_measured",
            "reason": "Repairs were made by an agent; no human correction session was timed.",
        },
    }
    output.mkdir(parents=True, exist_ok=True)
    for condition, proposal in prepared.items():
        (output / f"{condition}.json").write_text(
            proposal.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
    (output / "repair_manifest.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report
