"""Reproduce the real legacy workflows twice without generating target code."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from .models import RuntimeRequest
from .redmine import FIXTURE_EPOCH, RedmineReference


def _steps(fixture: dict[str, Any]) -> list[tuple[str, RuntimeRequest]]:
    issue_path = f"/issues/{fixture['issue_id']}.json"
    create_payload = {
        "issue": {
            "project_id": fixture["project_id"],
            "tracker_id": fixture["tracker_id"],
            "subject": "Migrating a real legacy workflow",
            "description": "Synthetic scenario.",
        }
    }
    specifications = [
        ("get_owned", "GET", issue_path, "alice", None),
        ("deny_outsider", "GET", issue_path, "outsider", None),
        ("deny_anonymous", "GET", issue_path, "anonymous", None),
        ("create_issue", "POST", "/issues.json", "alice", create_payload),
        (
            "empty_subject",
            "POST",
            "/issues.json",
            "alice",
            {
                "issue": {
                    "project_id": fixture["project_id"],
                    "tracker_id": fixture["tracker_id"],
                    "subject": "",
                }
            },
        ),
        (
            "skip_status",
            "PUT",
            issue_path,
            "alice",
            {
                "issue": {
                    "status_id": fixture["status_ids"]["closed"],
                    "notes": "Skipped transition probe",
                }
            },
        ),
        (
            "advance_status",
            "PUT",
            issue_path,
            "alice",
            {
                "issue": {
                    "status_id": fixture["status_ids"]["in_progress"],
                    "notes": "Observed transition",
                }
            },
        ),
        (
            "close_issue",
            "PUT",
            issue_path,
            "alice",
            {"issue": {"status_id": fixture["status_ids"]["closed"], "notes": "Closing fixture"}},
        ),
        ("get_closed", "GET", issue_path + "?include=journals", "alice", None),
    ]
    return [
        (
            name,
            RuntimeRequest(
                method=method,
                path=path,
                actor=actor,
                json_body=payload,
                fixture_epoch=FIXTURE_EPOCH + 60 * (index + 1),
            ),
        )
        for index, (name, method, path, actor, payload) in enumerate(specifications)
    ]


def capture_reference(reference_factory: Callable = RedmineReference) -> dict[str, Any]:
    with reference_factory() as runtime:
        metadata = runtime.describe()
        fixture = runtime.fixture
        steps = []
        for name, request in _steps(fixture):
            before = runtime.snapshot()
            response = runtime.request(request)
            after = runtime.snapshot()
            steps.append(
                {
                    "step_id": name,
                    "request": request.model_dump(mode="json"),
                    "response": response.model_dump(mode="json", by_alias=True),
                    "database_before": before,
                    "database_after": after,
                }
            )
        return {"runtime": metadata, "fixture": fixture, "steps": steps}


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def verify_reference(
    output_directory: str | Path,
    *,
    reference_factory: Callable = RedmineReference,
) -> dict[str, Any]:
    """A passed gate proves reproducibility of the observed scope, not a migration."""
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    captures = []
    for index in range(2):
        captured = capture_reference(reference_factory)
        (output / f"reference_trace_{index + 1}.json").write_text(
            json.dumps(captured, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        captures.append(captured)
    hashes = [_digest(captured) for captured in captures]
    by_step = {step["step_id"]: step for step in captures[0]["steps"]}
    checks = {
        "independent_replays_match": hashes[0] == hashes[1],
        "reference_read_succeeds": by_step["get_owned"]["response"]["status"] == 200,
        "outsider_denied": by_step["deny_outsider"]["response"]["status"] in {401, 403, 404},
        "issue_creation_succeeds": by_step["create_issue"]["response"]["status"] == 201,
        "status_update_succeeds": by_step["advance_status"]["response"]["status"] == 204,
        "journal_changes_observed": bool(by_step["close_issue"]["database_after"]["journals"]),
        "network_disabled": all(c["runtime"]["network"] == "none" for c in captures),
        "root_filesystem_read_only": all(c["runtime"]["read_only_root"] for c in captures),
        "unprivileged_user": all(c["runtime"]["user"] == "999:999" for c in captures),
        "no_published_ports": all(not c["runtime"]["published_ports"] for c in captures),
    }
    result = {
        "schema_version": "1.0",
        "gate": "legacy_reference_reproducibility",
        "status": "passed" if all(checks.values()) else "failed",
        "checks": checks,
        "trace_sha256": hashes,
        "step_count_per_replay": len(captures[0]["steps"]),
        "runtime": captures[0]["runtime"],
        "migration_performed": False,
        "limits": [
            "Observations cover declared synthetic issue workflows and selected database tables.",
            "A deterministic test clock is injected; monotonic timeout clocks remain real.",
            "Production data and security certification are outside this reference gate.",
        ],
    }
    (output / "reference_gate.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result
