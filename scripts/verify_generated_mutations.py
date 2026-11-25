"""Replay curated faults in a passing generated update; guidance only, no model calls."""

import argparse
import json
from pathlib import Path

from legacylift.modernization.generated_mutations import run_generated_mutations

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path(".legacylift"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_generated_mutations(args.home, args.run_id, args.output)
        print(
            json.dumps(
                {
                    key: report[key]
                    for key in (
                        "status",
                        "run_id",
                        "mutation_count",
                        "detected_count",
                        "held_out_read",
                        "model_requests",
                    )
                },
                indent=2,
            )
        )
        raise SystemExit(0 if report["status"] == "passed" else 1)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Mutation measurement rejected: {type(error).__name__}\n")
