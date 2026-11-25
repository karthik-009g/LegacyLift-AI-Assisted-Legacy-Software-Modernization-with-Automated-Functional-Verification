"""Post-hoc sensitivity checks against the genuine passing update implementation.

These curated mutations cover this selected implementation, not arbitrary candidates.
Only guidance expectations are used; no model request or original-source edit occurs.
"""

from __future__ import annotations

import json
from pathlib import Path

from .contracts import canonical_hash
from .study import evaluate_source, write_json


def update_source_mutations(source: str) -> list[dict]:
    variants = []

    def change(name, scenario, path, old, new, count=1):
        if source.count(old) != count:
            raise ValueError(f"mutation anchor is not unique/complete: {name}")
        mutated = source.replace(old, new)
        variants.append(
            {
                "mutation_id": name,
                "scenario_id": scenario,
                "expected_mismatch_path": path,
                "source": mutated,
                "source_sha256": canonical_hash(mutated),
            }
        )

    change(
        "authentication_status",
        "update.anonymous",
        "steps[0].response.status",
        "return None, 401",
        "return None, 200",
        count=2,
    )
    change(
        "authorization_status",
        "update.outsider",
        "steps[0].response.status",
        'if not user_project_membership(user["id"], project_id):\n'
        "            return Response(status_code=403,",
        'if not user_project_membership(user["id"], project_id):\n'
        "            return Response(status_code=200,",
    )
    change(
        "transition_validation",
        "update.skip_transition",
        "steps[0].database_after.issues[0].status_id",
        "allowed = wf is not None",
        "allowed = True",
    )
    change(
        "status_persistence",
        "update.advance",
        "steps[0].database_after.issues[0].status_id",
        'updates["status_id"] = new_status_id',
        'updates["status_id"] = issue_row["status_id"]',
    )
    change(
        "lock_counter",
        "update.advance",
        "steps[0].database_after.issues[0].lock_version",
        'issue_row["lock_version"] + 1',
        'issue_row["lock_version"]',
    )
    change(
        "closure_timestamp",
        "update.close",
        "steps[1].database_after.issues[0].closed_on",
        'if status_row and status_row["is_closed"]:',
        "if False:",
    )
    change(
        "audit_persistence",
        "update.advance",
        "steps[0].database_after.journals.length",
        "if notes is not None or allowed:",
        "if False:",
    )
    change(
        "audit_old_value",
        "update.advance",
        "steps[0].database_after.journal_details[0].old_value",
        '"old": str(issue_row["status_id"])',
        '"old": "999"',
    )
    change(
        "authentication_body",
        "update.anonymous",
        "steps[0].response.body_empty",
        "return Response(status_code=err, headers=",
        'return Response(content=b"x", status_code=err, headers=',
    )
    return variants


def run_generated_mutations(
    home: Path, run_id: str, output: Path, *, evaluator=evaluate_source
) -> dict:
    if not (1 <= len(run_id) <= 64 and run_id.isascii() and run_id.isalnum()):
        raise ValueError("invalid run identifier")
    if output.exists():
        raise ValueError("preserve the previous measurement; select a new output path")
    directory = home / "runs" / run_id
    saved = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    source = (directory / "app.py").read_text(encoding="utf-8")
    source_digest = canonical_hash(source)
    attempts = saved.get("attempts", [])
    if (
        saved.get("status") != "passed"
        or saved.get("workflow") != "update"
        or not attempts
        or attempts[-1].get("source_sha256") != source_digest
        or attempts[-1].get("provenance", {}).get("provider")
        not in {"groq", "gemini", "openrouter"}
        or attempts[-1].get("provenance", {}).get("seeded")
    ):
        raise ValueError("requires an unchanged, guidance-passing generated update candidate")
    variants = update_source_mutations(source)
    report = {
        "status": "running",
        "measurement_version": 2,
        "implementation_sha256": canonical_hash(Path(__file__).read_text(encoding="utf-8")),
        "mutation_plan_sha256": canonical_hash(
            [{k: v for k, v in variant.items() if k != "source"} for variant in variants]
        ),
        "scope": "generated_update_source_mutations",
        "run_id": run_id,
        "source_sha256": source_digest,
        "candidate_kind": "model_generated_update",
        "model_requests": 0,
        "held_out_read": False,
        "original_source_modified": False,
        "planned_mutation_count": len(variants),
        "results": [],
        "security_certified": False,
        "limitations": [
            "Curated after this implementation was inspected; not an unbiased mutation sample.",
            "Only the six declared update guidance scenarios are exercised.",
            "Source anchors are specific to this implementation, not a general mutation engine.",
        ],
    }

    def measure(code):
        return evaluator(code, home, workflow="update", split="guidance")

    try:
        baseline = measure(source)
        report["baseline"] = {
            k: baseline[k] for k in ("status", "scenario_count", "passed_count", "source_sha256")
        }
        if baseline["status"] != "passed" or baseline["passed_count"] != 6:
            report["status"] = "baseline_mismatch"
        else:
            for variant in variants:
                measured = measure(variant["source"])
                target = next(
                    (r for r in measured["results"] if r["scenario_id"] == variant["scenario_id"]),
                    None,
                )
                detected = (
                    target is not None
                    and not target["passed"]
                    and any(
                        diff["path"] == variant["expected_mismatch_path"]
                        for diff in target.get("mismatches", [])
                    )
                )
                report["results"].append(
                    {k: v for k, v in variant.items() if k != "source"}
                    | {
                        "detected": detected,
                        "status": measured["status"],
                        "passed_count": measured["passed_count"],
                        "scenario_count": measured["scenario_count"],
                        "target_mismatches": target.get("mismatches", []) if target else [],
                    }
                )
                write_json(output, report)
            report["status"] = (
                "passed" if all(r["detected"] for r in report["results"]) else "failed"
            )
    except (RuntimeError, OSError, ValueError) as error:
        # Boot/transport/measurement failures never count as detected semantic faults.
        report["status"] = "measurement_failed"
        report["failure_type"] = type(error).__name__
    report["mutation_count"] = len(report["results"])
    report["detected_count"] = sum(r["detected"] for r in report["results"])
    write_json(output, report)
    return report
