"""Run measured local isolation checks without model credentials or frozen oracles."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from legacylift.modernization.security_assessment import assess_runtime_isolation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/v2/runtime_isolation_assessment.json")
    )
    arguments = parser.parse_args()
    report = assess_runtime_isolation()
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "passed_checks": sum(report["checks"].values()),
                "checks": len(report["checks"]),
                "report": str(arguments.output),
                "certified_secure": False,
            }
        )
    )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
