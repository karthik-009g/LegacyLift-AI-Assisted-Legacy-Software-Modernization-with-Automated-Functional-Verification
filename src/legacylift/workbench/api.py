"""Loopback workbench; the API never imports generated application modules."""

from __future__ import annotations

import hashlib
import io
import json
import os
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from legacylift.modernization import model_profiles, openrouter
from legacylift.modernization.call_ledger import CallLedger
from legacylift.modernization.contracts import canonical_hash, contract_manifest
from legacylift.modernization.generation import GEMINI_MODEL, configured_groq_model
from legacylift.modernization.pipeline import can_resume_prompt_rebuild
from legacylift.modernization.security import approval_review_passes
from legacylift.runtimes.redmine import ASSETS, REDMINE_SOURCE_COMMIT

from .jobs import Dispatcher
from .store import Event, Store


class StartJob(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["prepare", "migrate", "finalize"]
    workflow: Literal["read", "create", "update", "all"] = "read"
    condition: Literal["source_only", "runtime_only", "hybrid"] = "hybrid"
    provider: Literal["auto", "groq", "gemini", "openrouter"] | None = None
    max_repairs: int = Field(default=2, ge=0, le=2)
    run_id: str | None = Field(default=None, pattern="^[A-Za-z0-9]{1,64}$")
    retry_failed_call: bool = False
    staged_read: bool | None = None
    groq_reasoning_effort: Literal["low", "medium", "high"] | None = None


class ReviewApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reviewer: str = Field(min_length=1, max_length=100)
    notes: str = Field(min_length=1, max_length=2000)
    source_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    reviewed_source_and_limitations: Literal[True]


def create_app(home: Path | None = None, *, start_jobs=True) -> FastAPI:
    home = (home or Path(os.environ.get("LEGACYLIFT_HOME", ".legacylift"))).resolve()
    store = Store(home)
    dispatcher = Dispatcher(store)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        store.recover_stale()
        if start_jobs:
            for job in store.list():
                if job["state"] == "queued":
                    dispatcher.submit(job["id"])
        yield
        dispatcher.close()

    app = FastAPI(title="LegacyLift migration workbench", version="2.0.0", lifespan=lifespan)
    app.state.store, app.state.dispatcher = store, dispatcher

    @app.middleware("http")
    async def local_access(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        origin = request.headers.get("origin")
        allowed = {"127.0.0.1", "localhost", "testserver"}
        if host not in allowed:
            return Response("Loopback access only", status_code=403)
        if origin and origin not in {
            f"http://{request.headers.get('host')}",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        }:
            return Response("Cross-origin access denied", status_code=403)
        if (
            request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.headers.get("x-legacylift-client") != "workbench"
        ):
            return Response("Workbench client header required", status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response

    def run_directory(run_id: str) -> Path:
        if not (1 <= len(run_id) <= 64 and run_id.isascii() and run_id.isalnum()):
            raise HTTPException(422, "Invalid run identifier")
        directory = home / "runs" / run_id
        if not directory.is_dir():
            raise HTTPException(404, "Run not found")
        return directory

    def candidate_source(directory: Path, candidate: Path | None = None) -> str:
        resolved_directory = directory.resolve()
        resolved_candidate = (candidate or directory / "app.py").resolve()
        if (
            not resolved_candidate.is_relative_to(resolved_directory)
            or not resolved_candidate.is_file()
        ):
            raise HTTPException(409, "Candidate source is unavailable in this run")
        return resolved_candidate.read_text(encoding="utf-8")

    def read_json(path: Path):
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None

    @app.get("/api/health")
    def health():
        return {
            "status": "ok",
            "project": "Redmine 4.2.10 → Python 3.14/FastAPI",
            "source_commit": REDMINE_SOURCE_COMMIT,
            "contract": contract_manifest(),
            "prepared": (home / "study/oracle.json").is_file(),
            "synthetic_fixture": (home / "study/synthetic_fixture.json").is_file(),
            "providers": {
                "groq": {
                    "configured": bool(os.environ.get("GROQ_API_KEY")),
                    "model": configured_groq_model(),
                },
                "gemini": {
                    "configured": bool(os.environ.get("GEMINI_API_KEY")),
                    "model": os.environ.get("LEGACYLIFT_GEMINI_MODEL") or GEMINI_MODEL,
                    "prompt_byte_limit": model_profiles.PROMPT_BYTE_LIMIT,
                    "max_completion_tokens": model_profiles.MAX_COMPLETION_TOKENS,
                },
                "openrouter": {
                    "configured": bool(os.environ.get("OPENROUTER_API_KEY")),
                    "model": openrouter.configured_model(),
                    "models": list(openrouter.FREE_MODELS),
                    "prompt_byte_limit": model_profiles.PROMPT_BYTE_LIMIT,
                    "max_completion_tokens": openrouter.MAX_COMPLETION_TOKENS,
                    "free_only": True,
                },
            },
            "execution": "rq" if os.environ.get("LEGACYLIFT_REDIS_URL") else "local-single-worker",
        }

    @app.get("/api/evidence")
    def evidence(workflow: Literal["read", "create", "update"] = "read"):
        path = home / "evidence/redmine.json"
        if not path.is_file():
            raise HTTPException(409, "Prepare the reference first")
        data = read_json(path)
        return {
            k: data[k]
            for k in ("method_count", "source_file_count", "parse_error_files", "unknowns")
        } | {
            "sources": data["workflows"][workflow],
            "rails_inferences": [
                r
                for r in data["rails_inferences"]
                if r["path"] in {"app/models/issue.rb", "app/controllers/issues_controller.rb"}
            ][:100],
        }

    @app.get("/api/jobs")
    def jobs():
        return store.list()

    @app.post("/api/jobs", status_code=202)
    def start_job(payload: StartJob):
        if payload.kind != "migrate" and (payload.staged_read or payload.groq_reasoning_effort):
            raise HTTPException(422, "Generation settings apply only to migration jobs")
        if payload.kind != "prepare" and not (home / "study/oracle.json").exists():
            raise HTTPException(409, "Prepare the reference before migration or verification")
        if payload.kind == "finalize":
            if not payload.run_id:
                raise HTTPException(422, "run_id required for final verification")
            run_directory(payload.run_id)
            parameters = {"run_id": payload.run_id}
        elif payload.kind == "migrate":
            staged_read = bool(payload.staged_read)
            reasoning = payload.groq_reasoning_effort
            effective_provider = payload.provider
            if payload.retry_failed_call and not payload.run_id:
                raise HTTPException(422, "run_id required to retry a failed provider call")
            if payload.run_id:
                directory = run_directory(payload.run_id)
                result = read_json(directory / "result.json")
                settings = generation_settings(directory)
                if (
                    payload.staged_read is not None
                    and payload.staged_read != settings["staged_read"]
                ):
                    raise HTTPException(409, "Run generation mode is immutable")
                staged_read = settings["staged_read"]
                if reasoning is not None and reasoning != settings["groq_reasoning_effort"]:
                    raise HTTPException(409, "Run reasoning effort is immutable")
                effective_provider = effective_provider or (result or {}).get("provider_policy")
                if staged_read and effective_provider == "groq":
                    reasoning = settings["groq_reasoning_effort"]
                budget = CallLedger(home).summary_for_run(payload.run_id)
                if budget is not None and budget["remaining"] == 0:
                    raise HTTPException(
                        409, "Run request budget is exhausted; no retry is available"
                    )
                has_interrupted_call = bool(list(directory.glob("call-*.json")))
                if result is None and not has_interrupted_call:
                    raise HTTPException(409, "Run has no interrupted provider request to resume")
                if result is not None:
                    if result.get("status") not in {"provider_paused", "provider_failed"}:
                        raise HTTPException(409, "Only a paused provider run can be resumed")
                    if result.get("workflow") != payload.workflow:
                        raise HTTPException(409, "Run workflow is immutable")
                    if result.get("condition") != payload.condition:
                        raise HTTPException(409, "Run evidence condition is immutable")
                    if result.get("max_repairs", payload.max_repairs) != payload.max_repairs:
                        raise HTTPException(409, "Run repair budget is immutable")
                    if (
                        payload.provider is not None
                        and result.get("provider_policy") is not None
                        and result["provider_policy"] != payload.provider
                    ):
                        raise HTTPException(409, "Run provider policy is immutable")
                    failure = result.get("failure", {})
                    if (
                        payload.retry_failed_call
                        and failure.get("retryable") is False
                        and not can_resume_prompt_rebuild(directory, failure)
                    ):
                        raise HTTPException(409, "Narrow the migration scope instead of retrying")
            if staged_read and (
                payload.workflow != "read"
                or payload.condition != "hybrid"
                or effective_provider not in {"groq", "gemini"}
            ):
                raise HTTPException(
                    422, "Separate endpoints require read/hybrid with fixed Groq or Gemini"
                )
            if reasoning is not None and (not staged_read or effective_provider != "groq"):
                raise HTTPException(
                    422, "Reasoning selection requires separate endpoints with Groq"
                )
            parameters = payload.model_dump(
                include={
                    "workflow",
                    "condition",
                    "provider",
                    "max_repairs",
                    "run_id",
                    "retry_failed_call",
                }
            )
            if staged_read:
                parameters["staged_read"] = True
            if reasoning is not None:
                parameters["groq_reasoning_effort"] = reasoning
        else:
            if any(
                job["kind"] == "prepare" and job["state"] in {"queued", "running"}
                for job in store.list()
            ):
                raise HTTPException(409, "Reference preparation already queued or running")
            parameters = {}
        job = store.create(payload.kind, parameters)
        if start_jobs:
            dispatcher.submit(job["id"])
        return job

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        try:
            return store.get(job_id)
        except KeyError:
            raise HTTPException(404, "Job not found") from None

    @app.get("/api/jobs/{job_id}/events")
    def events(job_id: str, after: int = 0):
        with Session(store.engine) as session:
            return [
                {
                    "id": event.id,
                    "message": event.message,
                    "progress": event.progress,
                    "created_at": event.created_at.isoformat(),
                }
                for event in session.scalars(
                    select(Event)
                    .where(Event.job_id == job_id, Event.id > after)
                    .order_by(Event.id)
                    .limit(200)
                )
            ]

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str):
        try:
            return store.cancel(job_id)
        except KeyError:
            raise HTTPException(404, "Job not found") from None

    @app.get("/api/runs")
    def runs():
        directory = home / "runs"
        if not directory.exists():
            return []
        return [
            read_json(path)
            for path in sorted(
                directory.glob("*/result.json"), key=lambda p: p.stat().st_mtime, reverse=True
            )
        ]

    @app.get("/api/runs/{run_id}")
    def run(run_id: str):
        directory = run_directory(run_id)
        result = read_json(directory / "result.json")
        if result:
            budget = CallLedger(home).summary_for_run(run_id)
            if budget is not None:
                result["call_ledger"] = budget
        if result and result.get("failure", {}).get("category") == "prompt_too_large":
            result["failure"]["local_rebuild_available"] = can_resume_prompt_rebuild(
                directory, result["failure"]
            )
        candidate = directory / "app.py"
        if not candidate.is_file() and result and result.get("candidate_path"):
            candidate = Path(result["candidate_path"])
        try:
            source = candidate_source(directory, candidate)
        except HTTPException:
            source = None
        final = read_json(directory / "held-out.json")
        approval = store.approval(run_id)
        source_digest = canonical_hash(source) if source is not None else None
        report_digest = canonical_hash(final) if final else None
        if (
            not result
            or result.get("status") != "passed"
            or not final
            or final.get("status") != "passed"
            or result.get("held_out_report_sha256") != report_digest
            or final.get("source_sha256") != source_digest
            or not approval
            or approval.get("source_sha256") != source_digest
            or approval.get("verification_sha256") != report_digest
        ):
            approval = None
        return {
            "result": result,
            "generation_settings": generation_settings(directory),
            "source": source,
            "guidance": [read_json(path) for path in sorted(directory.glob("guidance-*.json"))],
            "held_out": final,
            "approval": approval,
        }

    def generation_settings(directory: Path) -> dict:
        context = read_json(directory / "context.json") or {}
        staged = bool(context.get("read_generation_strategy"))
        return {
            "staged_read": staged,
            "groq_reasoning_effort": context.get("groq_reasoning_effort") if staged else None,
        }

    @app.post("/api/runs/{run_id}/approve")
    def approve(run_id: str, payload: ReviewApproval):
        directory = run_directory(run_id)
        result = read_json(directory / "result.json")
        final = read_json(directory / "held-out.json")
        source = candidate_source(directory)
        if (
            not result
            or result["status"] != "passed"
            or not final
            or final["status"] != "passed"
            or result.get("held_out_report_sha256") != canonical_hash(final)
        ):
            raise HTTPException(409, "Guidance and held-out verification must pass before approval")
        digest = canonical_hash(source)
        if digest != payload.source_sha256 or digest != final["source_sha256"]:
            raise HTTPException(409, "Source checksum changed; verify again")
        if not approval_review_passes(source, result.get("attempts", [])):
            raise HTTPException(409, "Static review blocked this source")
        report_digest = canonical_hash(final)
        store.approve(run_id, digest, report_digest, payload.reviewer, payload.notes)
        return {
            "approved": True,
            "source_sha256": digest,
            "verification_sha256": report_digest,
            "security_certified": False,
        }

    @app.get("/api/runs/{run_id}/export")
    def export(run_id: str):
        directory = run_directory(run_id)
        source = candidate_source(directory)
        approval = store.approval(run_id)
        result = read_json(directory / "result.json")
        final = read_json(directory / "held-out.json")
        source_digest = canonical_hash(source)
        report_digest = canonical_hash(final) if final else None
        if (
            not result
            or result.get("status") != "passed"
            or not final
            or final.get("status") != "passed"
            or final.get("source_sha256") != source_digest
            or result.get("held_out_report_sha256") != report_digest
            or not approval
            or approval.get("source_sha256") != source_digest
            or approval.get("verification_sha256") != report_digest
        ):
            raise HTTPException(409, "Review and approve the current candidate before export")
        attempts = result.get("attempts", [])
        assembly = attempts[-1].get("source_assembly") if attempts else None
        if assembly is not None:
            if not isinstance(assembly, dict):
                raise HTTPException(409, "Candidate assembly metadata is malformed")
            line = assembly.get("model_first_line")
            lines = source.splitlines(keepends=True)
            if (
                type(line) is not int
                or not 2 <= line <= len(lines)
                or assembly.get("scaffold_sha256") != canonical_hash("".join(lines[: line - 1]))
                or assembly.get("fragment_sha256") != canonical_hash("".join(lines[line - 1 :]))
            ):
                raise HTTPException(409, "Candidate assembly checksums differ")

        def json_bytes(value):
            return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")

        entries = {
            "app.py": source.encode("utf-8"),
            "requirements.lock": (ASSETS / "target-requirements.lock").read_bytes(),
            "verification.json": json_bytes(final),
            "review.json": json_bytes(approval),
            "README.md": (
                "# Reviewed LegacyLift migration slice\n\n"
                "Derived from Redmine 4.2.10 (GPL-2.0-or-later). Retain upstream notices.\n"
                "Set DATABASE_URL to a compatible COPY of the Redmine database. No credentials "
                "or database are included. Install requirements.lock; run uvicorn app:app.\n"
                "Clock injection at /state/clock is a test contract: replace with a configurable "
                "production clock before deployment. This is a selected workflow migration, "
                "not a full Redmine replacement or security-certified production release.\n"
            ).encode("utf-8"),
        }
        if assembly is not None:
            entries["source-assembly.json"] = json_bytes(assembly)
        license_path = home / "repositories" / REDMINE_SOURCE_COMMIT / "doc/COPYING"
        if license_path.is_file():
            entries["COPYING"] = license_path.read_bytes()
        entries["manifest.json"] = json_bytes(
            {
                "format_version": 1,
                "run_id": run_id,
                "source_sha256": source_digest,
                "verification_sha256": report_digest,
                "files": {
                    name: hashlib.sha256(content).hexdigest() for name, content in entries.items()
                },
                "security_certified": False,
            }
        )
        stream = io.BytesIO()
        # Stored entries avoid compressor-version drift. Fixed metadata removes host/time drift.
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_STORED) as archive:
            for name, content in sorted(entries.items()):
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, content)
        payload = stream.getvalue()
        return Response(
            payload,
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="legacylift-{run_id[:8]}.zip"',
                "ETag": f'"{hashlib.sha256(payload).hexdigest()}"',
            },
        )

    dist = Path(os.environ.get("LEGACYLIFT_WEB_DIST", "web/dist")).resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        target = (dist / path).resolve()
        if not target.is_relative_to(dist):
            raise HTTPException(404)
        if path.startswith("api/"):
            raise HTTPException(404)
        if target.is_file():
            return FileResponse(target)
        if (dist / "index.html").is_file():
            return FileResponse(dist / "index.html")
        return Response("Build the workbench: cd web; npm ci; npm run build", status_code=503)

    return app
