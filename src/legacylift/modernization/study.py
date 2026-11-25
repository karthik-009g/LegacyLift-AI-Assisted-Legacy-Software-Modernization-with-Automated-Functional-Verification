"""Frozen reference oracles and independent target replay, outside application images."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Callable

from legacylift.runtimes.models import RuntimeRequest
from legacylift.runtimes.python_target import PythonTarget
from legacylift.runtimes.redmine import REDMINE_IMAGE, REDMINE_SOURCE_COMMIT, RedmineReference

from .contracts import canonical_hash, comparable, contract_manifest, differences, scenarios
from .frozen_study import evaluation_artifact, execution_inputs, seal_study
from .repository import import_redmine
from .ruby import write_ruby_evidence


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def capture(runtime, cases: list[dict], checkpoint: Callable = lambda *args: None) -> list[dict]:
    captures = []
    for index, case in enumerate(cases):
        checkpoint(f"Replaying {case['scenario_id']}", index / len(cases))
        runtime.reset()
        steps = []
        for payload in case["requests"]:
            checkpoint(f"Observing {case['scenario_id']}", index / len(cases))
            before = runtime.snapshot()
            response = runtime.request(RuntimeRequest.model_validate(payload))
            steps.append(
                {
                    "request": payload,
                    "response": response.model_dump(by_alias=True),
                    "database_before": before,
                    "database_after": runtime.snapshot(),
                }
            )
        captures.append({**case, "steps": steps})
    return captures


def prepare_study(workspace: Path, checkpoint: Callable = lambda *args: None) -> dict:
    checkpoint("Importing pinned public source", 0)
    source = import_redmine(workspace)
    evidence = write_ruby_evidence(
        Path(source["source_directory"]), workspace / "evidence/redmine.json"
    )
    directory = workspace / "study"
    manifest = contract_manifest()
    oracle_path = directory / "oracle.json"
    route_path = workspace / "evidence/runtime_routes.json"
    if oracle_path.exists():
        old = json.loads(oracle_path.read_text(encoding="utf-8"))
        if old["contract"] != manifest:
            raise ValueError("frozen study differs; version a new workspace instead of overwriting")
        seal_study(workspace)
        if not route_path.exists():
            checkpoint("Capturing pinned Rails route table", 0.05)
            with RedmineReference() as reference:
                routes = reference.issue_routes()
            write_json(route_path, _runtime_route_evidence(routes))
        return {
            "status": "already_prepared",
            "contract": manifest,
            "evidence": evidence,
            "runtime_route_count": len(
                json.loads(route_path.read_text(encoding="utf-8"))["routes"]
            ),
        }
    checkpoint("Booting isolated Ruby/Rails reference", 0.05)
    with RedmineReference() as reference:
        routes = reference.issue_routes()
        database = reference.fixture_bytes()
        actors = reference.actor_tokens()
        observations = capture(reference, scenarios(), checkpoint)
        oracle = {
            "contract": manifest,
            "runtime": reference.describe(),
            "fixture": reference.fixture,
            "scenarios": observations,
        }
    write_json(route_path, _runtime_route_evidence(routes))
    directory.mkdir(parents=True, exist_ok=True)
    # Synthetic credentials remain in ignored controller storage, never model context/artifacts.
    (directory / "fixture.sqlite3").write_bytes(database)
    write_json(directory / "actors.private.json", actors)
    os.chmod(directory / "actors.private.json", 0o600)
    os.chmod(directory / "fixture.sqlite3", 0o600)
    connection = sqlite3.connect(
        f"file:{(directory / 'fixture.sqlite3').as_posix()}?mode=ro", uri=True
    )
    schema = [
        {"table": row[0], "sql": row[1]}
        for row in connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]
    connection.close()
    write_json(directory / "schema.json", schema)
    oracle["oracle_sha256"] = canonical_hash(observations)
    write_json(oracle_path, oracle)
    write_json(
        directory / "guidance.json",
        {**oracle, "scenarios": [item for item in observations if item["split"] == "guidance"]},
    )
    seal_study(workspace)
    return {
        "status": "prepared",
        "contract": manifest,
        "evidence": evidence,
        "runtime_route_count": len(routes),
        "oracle_sha256": oracle["oracle_sha256"],
        "runtime": oracle["runtime"],
    }


def _runtime_route_evidence(routes: list[dict]) -> dict:
    return {
        "schema_version": "1.0",
        "kind": "pinned_runtime_route_table",
        "collection_command": "bundle exec rake routes",
        "repository": "https://github.com/redmine/redmine",
        "source_commit": REDMINE_SOURCE_COMMIT,
        "runtime_image": REDMINE_IMAGE,
        "route_count": len(routes),
        "routes_sha256": canonical_hash(routes),
        "routes": routes,
        "limits": [
            "Route facts describe verb, path, controller and action dispatch from Rails.",
            "They do not prove controller authorization, filters or downstream behavior.",
            "Only issue-controller show/create/update routes are retained.",
        ],
    }


def evaluate_source(
    source: str,
    workspace: Path,
    *,
    workflow: str | None = None,
    split: str = "guidance",
    checkpoint: Callable = lambda *args: None,
) -> dict:
    oracle, seal = evaluation_artifact(workspace, split)
    cases = [
        case
        for case in oracle["scenarios"]
        if (split == "all" or case["split"] == split)
        and (workflow is None or case["workflow"] == workflow)
    ]
    if not cases:
        raise ValueError("no scenarios match evaluation selection")
    database, actors = execution_inputs(workspace, seal)
    with PythonTarget(source, database, actors) as target:
        actual = capture(target, cases, checkpoint)
        runtime = target.describe()
        diagnostics = target.diagnostics()
    results = []
    for expected, observed in zip(cases, actual, strict=True):
        mismatches = []
        for index, (left, right) in enumerate(
            zip(expected["steps"], observed["steps"], strict=True)
        ):
            mismatches += differences(comparable(left), comparable(right), path=f"steps[{index}]")
        results.append(
            {
                "scenario_id": expected["scenario_id"],
                "split": expected["split"],
                "passed": not mismatches,
                "mismatches": mismatches[:80],
            }
        )
    passed = sum(result["passed"] for result in results)
    return {
        "status": "passed" if passed == len(results) else "compatibility_failed",
        "contract": oracle["contract"],
        "oracle_sha256": oracle["oracle_sha256"],
        "study_seal_sha256": seal["seal_sha256"],
        "source_sha256": canonical_hash(source),
        "split": split,
        "workflow": workflow,
        "scenario_count": len(results),
        "passed_count": passed,
        "match_rate": passed / len(results),
        "results": results,
        "runtime": runtime,
        "security_verdict": "not_assessed",
        "approved_deviations": [],
        "observations": actual,
        "diagnostics": diagnostics,
    }
