"""Persistent controller metadata; application fixture databases live elsewhere."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


def utcnow():
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="Queued")
    progress: Mapped[float] = mapped_column(Float, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    owner: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Event(Base):
    __tablename__ = "job_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    message: Mapped[str] = mapped_column(Text)
    progress: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    source_sha256: Mapped[str] = mapped_column(String(64))
    verification_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewer: Mapped[str] = mapped_column(String(100))
    notes: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def job_dict(job: Job) -> dict:
    return {
        name: (value.isoformat() if isinstance(value, datetime) else value)
        for name in (
            "id",
            "kind",
            "state",
            "parameters",
            "result",
            "message",
            "progress",
            "cancel_requested",
            "created_at",
            "updated_at",
        )
        for value in [getattr(job, name)]
    }


class Store:
    def __init__(self, home: Path, database_url: str | None = None):
        self.home = home.resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        url = (
            database_url
            or os.environ.get("LEGACYLIFT_DATABASE_URL")
            or ("sqlite:///" + (self.home / "metadata.sqlite3").as_posix())
        )
        self.engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args=(
                {"check_same_thread": False, "timeout": 30} if url.startswith("sqlite") else {}
            ),
        )

    def initialize(self):
        # Create missing tables and apply the additive approval change for existing workspaces.
        Base.metadata.create_all(self.engine)
        approval_columns = {
            column["name"] for column in inspect(self.engine).get_columns("approvals")
        }
        if "verification_sha256" not in approval_columns:
            with self.engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE approvals ADD COLUMN verification_sha256 VARCHAR(64)")
                )

    def create(self, kind: str, parameters: dict) -> dict:
        with Session(self.engine) as session:
            job = Job(id=uuid.uuid4().hex, kind=kind, parameters=parameters)
            session.add(job)
            session.commit()
            return job_dict(job)

    def get(self, job_id: str) -> dict:
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if not job:
                raise KeyError(job_id)
            return job_dict(job)

    def list(self) -> list[dict]:
        with Session(self.engine) as session:
            return [
                job_dict(job)
                for job in session.scalars(select(Job).order_by(Job.created_at.desc()).limit(100))
            ]

    def claim(self, job_id: str, owner: str) -> bool:
        with Session(self.engine) as session:
            changed = session.execute(
                update(Job)
                .where(Job.id == job_id, Job.state == "queued", Job.cancel_requested.is_(False))
                .values(state="running", owner=owner, message="Starting", updated_at=utcnow())
            ).rowcount
            session.commit()
            return changed == 1

    def checkpoint(self, job_id: str, owner: str, message: str, progress: float) -> bool:
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if not job or job.owner != owner or job.cancel_requested:
                return False
            job.message, job.progress, job.updated_at = (
                message[:1000],
                min(0.99, max(0, progress)),
                utcnow(),
            )
            session.add(Event(job_id=job_id, message=job.message, progress=job.progress))
            session.commit()
            return True

    def finish(self, job_id: str, owner: str, state: str, *, result=None, message=""):
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if not job or job.owner != owner:
                return
            job.state = "cancelled" if job.cancel_requested else state
            job.result, job.message, job.updated_at = result, message[:2000], utcnow()
            if state == "succeeded":
                job.progress = 1
            session.add(Event(job_id=job_id, message=job.message, progress=job.progress))
            session.commit()

    def cancel(self, job_id: str) -> dict:
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if not job:
                raise KeyError(job_id)
            if job.state in {"queued", "running", "cancelling"}:
                job.cancel_requested = True
                job.state = "cancelled" if job.state == "queued" else "cancelling"
                job.message = "Cancellation requested; active bounded operation will finish first"
                job.updated_at = utcnow()
                session.commit()
            return job_dict(job)

    def recover_stale(self, *, after_seconds=600) -> int:
        # Do not reset a healthy worker's active lease when the API restarts.
        with Session(self.engine) as session:
            count = session.execute(
                update(Job)
                .where(
                    Job.state.in_(["running", "cancelling"]),
                    Job.updated_at < utcnow() - timedelta(seconds=after_seconds),
                )
                .values(
                    state="interrupted",
                    message="Worker lease expired; start a new job explicitly",
                    updated_at=utcnow(),
                )
            ).rowcount
            session.commit()
            return count

    def approve(
        self,
        run_id: str,
        source_sha256: str,
        verification_sha256: str,
        reviewer: str,
        notes: str,
    ):
        with Session(self.engine) as session:
            session.merge(
                Approval(
                    run_id=run_id,
                    source_sha256=source_sha256,
                    verification_sha256=verification_sha256,
                    reviewer=reviewer,
                    notes=notes,
                )
            )
            session.commit()

    def approval(self, run_id: str) -> dict | None:
        with Session(self.engine) as session:
            row = session.get(Approval, run_id)
            return (
                {
                    "source_sha256": row.source_sha256,
                    "verification_sha256": row.verification_sha256,
                    "reviewer": row.reviewer,
                    "notes": row.notes,
                }
                if row
                else None
            )
