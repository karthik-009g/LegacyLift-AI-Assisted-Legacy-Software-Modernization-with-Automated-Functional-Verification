"""Measure AST policy coverage with inert source strings, without executing candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from legacylift.modernization import security

PRELUDE = "from fastapi import FastAPI\napp = FastAPI()\n"
SPECIMENS = (
    ("ordinary_app", False, "def value():\n    return {'ready': True}\n"),
    ("direct_process_import", True, "import subprocess\n"),
    ("direct_shell_call", True, "import os\nos.system('true')\n"),
    ("direct_eval", True, "eval('1 + 1')\n"),
    ("direct_dynamic_import", True, "__import__('subprocess')\n"),
    ("eval_alias", True, "runner = eval\nrunner('1 + 1')\n"),
    ("import_alias", True, "loader = __import__\nloader('subprocess')\n"),
    ("reflected_shell_call", True, "import os\ngetattr(os, 'system')('true')\n"),
)


def assess() -> dict:
    policy = Path(security.__file__).read_bytes()
    cases = []
    for name, prohibited, fragment in SPECIMENS:
        source = PRELUDE + fragment
        # review_source parses source text with ast.parse. Never eval/exec/import it.
        review = security.review_source(source)
        blocked = review["status"] == "blocked"
        cases.append(
            {
                "specimen": name,
                "source": source,
                "source_utf8_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
                "exercises_prohibited_capability": prohibited,
                "policy_status": review["status"],
                "rules": sorted({finding["rule"] for finding in review.get("findings", [])}),
                "static_miss": prohibited and not blocked,
                "ordinary_app_blocked": not prohibited and blocked,
            }
        )
    misses = sum(case["static_miss"] for case in cases)
    return {
        "version": 1,
        "policy_version": security.STATIC_POLICY_VERSION,
        "policy_sha256": hashlib.sha256(policy).hexdigest(),
        "status": "open_static_policy_gaps" if misses else "specimens_matched_expectations",
        "candidate_execution": False,
        "provider_requests": 0,
        "held_out_read": False,
        "certified_secure": False,
        "specimen_count": len(cases),
        "prohibited_specimens": sum(case["exercises_prohibited_capability"] for case in cases),
        "static_misses": misses,
        "ordinary_app_false_positives": sum(case["ordinary_app_blocked"] for case in cases),
        "cases": cases,
        "limitations": [
            "Curated syntactic specimens, not an exhaustive adversarial benchmark.",
            "No candidate code executed. A static miss does not prove a container escape "
            "or successful command/network operation.",
            "Aliases and reflection demonstrate why the AST policy is not a sandbox. "
            "Restricted runtime execution remains a separate boundary.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("refusing to overwrite a recorded assessment")
    report = assess()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}))


if __name__ == "__main__":
    main()
