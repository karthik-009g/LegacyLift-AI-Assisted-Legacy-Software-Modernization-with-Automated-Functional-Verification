"""Predeclared scenario identities and strict external observation comparison."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from legacylift.runtimes.models import RuntimeRequest
from legacylift.runtimes.redmine import FIXTURE_EPOCH

CONTRACT_VERSION = "redmine-issues-2"
GUIDANCE_PER_WORKFLOW = 6


def scenarios() -> list[dict]:
    """Six guidance and four held-out scenarios for each workflow, frozen before generation."""

    def read(path="/issues/1.json", actor="alice"):
        return {"method": "GET", "path": path, "actor": actor}

    def create(subject="A migrated issue", actor="alice", **fields):
        issue = {"project_id": 1, "tracker_id": 1, "subject": subject, **fields}
        return {
            "method": "POST",
            "path": "/issues.json",
            "actor": actor,
            "json_body": {"issue": issue},
        }

    def update(actor="alice", issue_id=1, **fields):
        return {
            "method": "PUT",
            "path": f"/issues/{issue_id}.json",
            "actor": actor,
            "json_body": {"issue": fields},
        }

    specifications = {
        "create": [
            ("basic", [create(description="Synthetic description")]),
            ("blank", [create("")]),
            ("outsider", [create(actor="outsider")]),
            ("anonymous", [create(actor="anonymous")]),
            ("long_subject", [create("x" * 256)]),
            ("unknown_project", [create(project_id=99999)]),
            ("unicode", [create("Résumé → 移行", description="Line one\nLine two")]),
            ("whitespace", [create("   ")]),
            ("invalid_tracker", [create(tracker_id=99999)]),
            ("mass_assignment", [create(author_id=6, project_id=1, status_id=5, is_private=True)]),
        ],
        "read": [
            ("owned", [read()]),
            ("outsider", [read(actor="outsider")]),
            ("anonymous", [read(actor="anonymous")]),
            ("missing", [read("/issues/99999.json")]),
            ("journals_empty", [read("/issues/1.json?include=journals")]),
            ("after_create", [create(), read("/issues/2.json")]),
            ("outsider_missing", [read("/issues/99999.json", "outsider")]),
            ("unknown_include", [read("/issues/1.json?include=unrecognized")]),
            ("after_close", [update(status_id=2), update(status_id=5), read()]),
            ("after_notes", [update(notes="Audit note"), read("/issues/1.json?include=journals")]),
        ],
        "update": [
            ("advance", [update(status_id=2, notes="Started")]),
            ("skip_transition", [update(status_id=5, notes="Ignored status, retained note")]),
            ("close", [update(status_id=2), update(status_id=5, notes="Finished")]),
            ("outsider", [update(actor="outsider", status_id=2)]),
            ("anonymous", [update(actor="anonymous", status_id=2)]),
            ("missing", [update(issue_id=99999, status_id=2)]),
            ("notes_only", [update(notes="Note without a state change")]),
            ("invalid_status", [update(status_id=99999, notes="Invalid status probe")]),
            ("empty_note", [update(status_id=2, notes="")]),
            ("repeat", [update(status_id=2, notes="First"), update(status_id=2, notes="Repeated")]),
        ],
    }
    result = []
    for workflow, cases in specifications.items():
        for index, (name, steps) in enumerate(cases):
            requests = [
                RuntimeRequest(**step, fixture_epoch=FIXTURE_EPOCH + 60 * (i + 1)).model_dump(
                    mode="json"
                )
                for i, step in enumerate(steps)
            ]
            result.append(
                {
                    "scenario_id": f"{workflow}.{name}",
                    "workflow": workflow,
                    "split": "guidance" if index < GUIDANCE_PER_WORKFLOW else "held_out",
                    "requests": requests,
                }
            )
    return result


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def contract_manifest() -> dict:
    cases = scenarios()
    return {
        "version": CONTRACT_VERSION,
        "scenario_sha256": canonical_hash(cases),
        "scenario_count": len(cases),
        "guidance_count": 18,
        "held_out_count": 12,
        "comparison": {
            "json": "strict types, keys, values and array order",
            "headers": ["content-type", "cache-control", "location"],
            "database": ["issues", "journals", "journal_details"],
            "ignored": [
                "HTTP serialization whitespace/body byte length",
                "unselected HTTP headers such as Date and request ID",
            ],
        },
        "scope": "Synthetic private project; selected REST endpoints; not full Redmine",
    }


def differences(expected: Any, actual: Any, path: str = "$", limit: int = 80) -> list[dict]:
    """Do not conflate bool/int, missing/null, errors, or duplicate array entries."""
    result: list[dict] = []

    def walk(left, right, location):
        if len(result) >= limit:
            return
        if type(left) is not type(right):
            result.append({"path": location, "expected": left, "actual": right, "reason": "type"})
        elif isinstance(left, dict):
            for key in sorted(left.keys() | right.keys()):
                child = f"{location}.{key}"
                if key not in left or key not in right:
                    result.append(
                        {
                            "path": child,
                            "expected": left.get(key),
                            "actual": right.get(key),
                            "reason": "missing_key",
                            "expected_present": key in left,
                            "actual_present": key in right,
                        }
                    )
                else:
                    walk(left[key], right[key], child)
                if len(result) >= limit:
                    return
        elif isinstance(left, list):
            if len(left) != len(right):
                result.append(
                    {
                        "path": location + ".length",
                        "expected": len(left),
                        "actual": len(right),
                        "reason": "length",
                    }
                )
            for i, (a, b) in enumerate(zip(left, right)):
                walk(a, b, f"{location}[{i}]")
        elif left != right:
            result.append({"path": location, "expected": left, "actual": right, "reason": "value"})

    walk(expected, actual, path)
    return result[:limit]


def comparable(observation: dict) -> dict:
    response = observation["response"]
    return {
        "response": {
            "status": response["status"],
            "json": response["json"],
            "body_empty": response["body_bytes"] == 0,
            "headers": {
                k: v
                for k, v in response["headers"].items()
                if k in {"content-type", "cache-control", "location"}
            },
        },
        "database_before": observation["database_before"],
        "database_after": observation["database_after"],
    }
