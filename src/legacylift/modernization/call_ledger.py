"""Durable request reservations shared by CLI/worker processes and seeded descendants."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .contracts import canonical_hash
from .protocol import code_hashes, input_hashes

CALL_LIMIT = 3


class CallBudgetExceeded(RuntimeError):
    pass


class CallLedger:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.runs = self.workspace / "runs"
        self.path = self.workspace / "model_calls.sqlite3"

    @contextmanager
    def transaction(self):
        self.workspace.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("call ledger must not be a symbolic link")
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in {0, 1}:
                raise ValueError("unsupported call ledger schema version")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS roots (
                    root_id TEXT PRIMARY KEY, manifest_json TEXT NOT NULL,
                    manifest_sha256 TEXT NOT NULL, legacy_calls INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY, root_id TEXT NOT NULL,
                    binding_json TEXT NOT NULL, binding_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS requests (
                    request_id INTEGER PRIMARY KEY AUTOINCREMENT, root_id TEXT NOT NULL,
                    run_id TEXT NOT NULL, attempt INTEGER NOT NULL, provider TEXT NOT NULL,
                    model TEXT NOT NULL, prompt_sha256 TEXT NOT NULL, reserved_at REAL NOT NULL,
                    state TEXT NOT NULL, outcome_json TEXT
                );
                PRAGMA user_version=1;
            """)
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _read_json(self, path: Path) -> dict:
        if path.is_symlink() or not path.resolve().is_relative_to(self.runs.resolve()):
            raise ValueError("trial metadata escaped the runs directory")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("trial metadata must be an object")
        return data

    def _parents(self) -> dict[str, str | None]:
        if self.runs.is_symlink():
            raise ValueError("runs directory must not be a symbolic link")
        parents = {}
        if not self.runs.is_dir():
            return parents
        for directory in self.runs.iterdir():
            if not directory.name.isalnum() or not directory.is_dir():
                continue
            if directory.is_symlink():
                raise ValueError("trial directory must not be a symbolic link")
            parent = None
            seed_path = directory / "seed.json"
            if seed_path.is_file():
                parent = self._read_json(seed_path).get("source_run_id")
                if not isinstance(parent, str) or not parent.isalnum():
                    raise ValueError("invalid seed lineage")
            result_path = directory / "result.json"
            if result_path.is_file():
                recorded = self._read_json(result_path).get("seeded_from_run_id")
                if recorded is not None and (
                    not isinstance(recorded, str) or not recorded.isalnum()
                ):
                    raise ValueError("invalid recorded seed lineage")
                if recorded and parent and recorded != parent:
                    raise ValueError("seed lineage differs between metadata records")
                parent = parent or recorded
            parents[directory.name] = parent
        return parents

    @staticmethod
    def _root(run_id: str, parents: dict[str, str | None]) -> str:
        seen = set()
        current = run_id
        while parents.get(current):
            if current in seen or len(seen) >= 100:
                raise ValueError("seed lineage is cyclic or exceeds its depth bound")
            seen.add(current)
            current = parents[current]
            if not isinstance(current, str) or not current.isalnum() or current not in parents:
                raise ValueError("seed ancestor is missing or invalid")
        return current

    def _legacy_calls(self, run_id: str) -> int:
        count = 0
        for path in (self.runs / run_id).glob("call-*.json"):
            call = self._read_json(path)
            expected = int(call.get("retry_number", 0)) + 1
            if expected < 1:
                raise ValueError("invalid request retry count")
            unknown = 2 if call.get("provider_policy", "auto") == "auto" else 1
            history = path.with_name(
                "provider-" + path.stem.removeprefix("call-") + ".attempts.jsonl"
            )
            groups = []
            if history.is_file():
                if history.is_symlink():
                    raise ValueError("request history must not be a symbolic link")
                for line in history.read_text(encoding="utf-8").splitlines():
                    event = json.loads(line)
                    if event.get("event") == "request_started":
                        groups.append(None)
                    elif event.get("event") in {"request_succeeded", "request_failed"}:
                        attempts = event.get("attempts", [])
                        consumed = (
                            sum(
                                item.get("error") != "key_not_configured"
                                and item.get("category") != "call_budget_exhausted"
                                for item in attempts
                            )
                            if attempts
                            else unknown
                        )
                        if groups and groups[-1] is None:
                            groups[-1] = consumed
                        else:
                            groups.append(consumed)
            count += sum(unknown if item is None else item for item in groups)
            count += max(0, expected - len(groups)) * unknown
        return count

    def register(self, run_id: str, binding: dict, *, manifest: dict | None = None) -> str:
        """Snapshot legacy history before a new call intent is written; never rewrite it."""
        if not run_id.isalnum() or len(run_id) > 128:
            raise ValueError("invalid ledger run identifier")
        with self.transaction() as connection:
            parents = self._parents()
            root_id = self._root(run_id, parents)
            root = connection.execute("SELECT * FROM roots WHERE root_id=?", (root_id,)).fetchone()
            if root is None:
                plan = manifest or {
                    "version": 1,
                    "scope": "exploratory",
                    "root_run_id": root_id,
                    "call_limit": CALL_LIMIT,
                }
                if plan.get("root_run_id") != root_id or plan.get("call_limit") != CALL_LIMIT:
                    raise ValueError("invalid trial call manifest")
                legacy = sum(
                    self._legacy_calls(name)
                    for name in parents
                    if self._root(name, parents) == root_id
                )
                connection.execute(
                    "INSERT INTO roots VALUES (?,?,?,?)",
                    (
                        root_id,
                        json.dumps(plan, sort_keys=True),
                        canonical_hash(plan),
                        legacy,
                    ),
                )
            else:
                plan = json.loads(root["manifest_json"])
                if canonical_hash(plan) != root["manifest_sha256"]:
                    raise ValueError("trial manifest checksum differs")
                if manifest is not None and manifest != plan:
                    raise ValueError("trial call manifest is immutable")
            if plan.get("scope") == "controlled" and root_id != run_id:
                raise ValueError("controlled trials cannot be extended through seeded runs")
            if plan.get("scope") == "controlled" and (
                plan.get("provider") not in {"groq", "gemini", "openrouter"}
                or binding.get("provider_policy") != plan["provider"]
                or not isinstance(plan.get("model"), str)
                or plan.get("code_sha256") != code_hashes()
                or plan.get("input_sha256") != input_hashes(self.workspace)
            ):
                raise ValueError("controlled trial provider/model/code/inputs differ from manifest")
            row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row:
                if (
                    row["root_id"] != root_id
                    or row["binding_sha256"] != canonical_hash(binding)
                    or canonical_hash(json.loads(row["binding_json"])) != row["binding_sha256"]
                ):
                    raise ValueError("trial ledger binding is immutable or differs from lineage")
            else:
                connection.execute(
                    "INSERT INTO runs VALUES (?,?,?,?)",
                    (
                        run_id,
                        root_id,
                        json.dumps(binding, sort_keys=True),
                        canonical_hash(binding),
                    ),
                )
        return root_id

    def reserve(
        self, run_id: str, attempt: int, provider: str, model: str, prompt_sha256: str
    ) -> int:
        if provider not in {"groq", "gemini", "openrouter"} or attempt not in {0, 1, 2}:
            raise ValueError("invalid provider request reservation")
        with self.transaction() as connection:
            member = connection.execute(
                "SELECT root_id FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if member is None:
                raise ValueError("trial must be registered before reserving a request")
            root_id = member["root_id"]
            root = connection.execute("SELECT * FROM roots WHERE root_id=?", (root_id,)).fetchone()
            plan = json.loads(root["manifest_json"])
            if canonical_hash(plan) != root["manifest_sha256"]:
                raise ValueError("trial manifest checksum differs")
            if plan.get("scope") == "controlled" and (
                provider != plan["provider"]
                or model != plan["model"]
                or plan.get("code_sha256") != code_hashes()
                or plan.get("input_sha256") != input_hashes(self.workspace)
            ):
                raise ValueError(
                    "controlled trial provider/model/code/inputs differ from its manifest"
                )
            used = (
                root["legacy_calls"]
                + connection.execute(
                    "SELECT COUNT(*) FROM requests WHERE root_id=?", (root_id,)
                ).fetchone()[0]
            )
            if used >= plan["call_limit"]:
                raise CallBudgetExceeded("Trial lineage has exhausted its three-request budget")
            previous = connection.execute(
                "SELECT model FROM requests WHERE root_id=? AND provider=? LIMIT 1",
                (root_id, provider),
            ).fetchone()
            if previous is not None and previous["model"] != model:
                raise ValueError("provider model is immutable within a trial lineage")
            cursor = connection.execute(
                "INSERT INTO requests "
                "(root_id,run_id,attempt,provider,model,prompt_sha256,reserved_at,state) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    root_id,
                    run_id,
                    attempt,
                    provider,
                    model,
                    prompt_sha256,
                    time.time(),
                    "reserved",
                ),
            )
            return cursor.lastrowid

    def finish(self, reservations: list[tuple[int, str]], outcomes: list[dict]) -> None:
        with self.transaction() as connection:
            for request_id, provider in reservations:
                match = next(
                    (
                        item
                        for item in outcomes
                        if item.get("provider") == provider
                        and item.get("error") != "key_not_configured"
                    ),
                    {},
                )
                safe = {
                    key: match[key]
                    for key in ("status", "category", "http_status", "error_type")
                    if key in match
                }
                encoded = json.dumps(safe, sort_keys=True)
                existing = connection.execute(
                    "SELECT * FROM requests WHERE request_id=?", (request_id,)
                ).fetchone()
                if existing is None:
                    raise ValueError("request reservation is missing")
                if existing["provider"] != provider:
                    raise ValueError("request outcome provider differs from its reservation")
                if existing["state"] != "reserved" and existing["outcome_json"] != encoded:
                    raise ValueError("recorded provider outcome is immutable")
                connection.execute(
                    "UPDATE requests SET state='recorded',outcome_json=? WHERE request_id=?",
                    (encoded, request_id),
                )

    def summary_for_run(self, run_id: str) -> dict | None:
        if not self.path.exists():
            return None
        with self.transaction() as connection:
            member = connection.execute(
                "SELECT root_id FROM runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return self.summary(member["root_id"]) if member is not None else None

    def summary(self, root_id: str) -> dict:
        with self.transaction() as connection:
            root = connection.execute("SELECT * FROM roots WHERE root_id=?", (root_id,)).fetchone()
            if root is None:
                raise ValueError("trial root is not registered")
            if canonical_hash(json.loads(root["manifest_json"])) != root["manifest_sha256"]:
                raise ValueError("trial manifest checksum differs")
            requests = connection.execute(
                "SELECT request_id,run_id,attempt,provider,model,"
                "prompt_sha256,state,outcome_json FROM requests WHERE root_id=? "
                "ORDER BY request_id",
                (root_id,),
            ).fetchall()
            return {
                "root_run_id": root_id,
                "call_limit": CALL_LIMIT,
                "legacy_requests_consumed": root["legacy_calls"],
                "reserved_requests": len(requests),
                "remaining": max(0, CALL_LIMIT - root["legacy_calls"] - len(requests)),
                "manifest_sha256": root["manifest_sha256"],
                "requests": [dict(row) for row in requests],
            }

    def validate_existing(self, run_id: str, binding: dict, *, seeded: bool) -> None:
        """A planned ID cannot be reused for a seed or altered no-call diagnostic run."""
        if not self.path.exists():
            return
        with self.transaction() as connection:
            member = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if member is None:
                return
            if (
                member["binding_sha256"] != canonical_hash(binding)
                or canonical_hash(json.loads(member["binding_json"])) != member["binding_sha256"]
            ):
                raise ValueError("trial ledger binding is immutable")
            root = connection.execute(
                "SELECT * FROM roots WHERE root_id=?", (member["root_id"],)
            ).fetchone()
            plan = json.loads(root["manifest_json"])
            if canonical_hash(plan) != root["manifest_sha256"]:
                raise ValueError("trial manifest checksum differs")
            if plan["scope"] == "controlled" and seeded:
                raise ValueError("controlled trial IDs cannot be used for seeded diagnostics")
            if plan["scope"] == "controlled" and (
                plan.get("code_sha256") != code_hashes()
                or plan.get("input_sha256") != input_hashes(self.workspace)
            ):
                raise ValueError("controlled study code or inputs changed before replay")
