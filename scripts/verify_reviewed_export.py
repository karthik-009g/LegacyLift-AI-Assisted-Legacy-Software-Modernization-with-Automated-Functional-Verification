"""Check/download an already approved local migration, without approving or generating it."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from legacylift.modernization.contracts import canonical_hash
from legacylift.workbench.api import create_app


def verify_export(home: Path, run_id: str, output: Path, *, replay=False) -> dict:
    if re.fullmatch(r"[A-Za-z0-9]{1,64}", run_id) is None:
        raise ValueError("invalid run identifier")
    with TestClient(create_app(home, start_jobs=False)) as client:
        first = client.get(f"/api/runs/{run_id}/export")
        second = client.get(f"/api/runs/{run_id}/export")
    if first.status_code != 200 or second.status_code != 200:
        raise ValueError("The exact saved source must already be verified and approved.")
    if first.content != second.content or first.headers["etag"] != second.headers["etag"]:
        raise ValueError("repeated downloads differ")
    with zipfile.ZipFile(io.BytesIO(first.content)) as archive:
        names = archive.namelist()
        required = {"app.py", "requirements.lock", "verification.json", "review.json", "COPYING"}
        if not required.issubset(names) or len(names) != len(set(names)):
            raise ValueError("required source, verification, review or upstream license missing")
        manifest = json.loads(archive.read("manifest.json"))
        actual = {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in names
            if name != "manifest.json"
        }
        if manifest["run_id"] != run_id or manifest["files"] != actual:
            raise ValueError("export manifest differs from archive content")
        source = archive.read("app.py").decode("utf-8")
        source_digest = canonical_hash(source)
        report = json.loads(archive.read("verification.json"))
        review = json.loads(archive.read("review.json"))
        if (
            source_digest != report["source_sha256"]
            or source_digest != review["source_sha256"]
            or source_digest != manifest["source_sha256"]
            or canonical_hash(report) != review["verification_sha256"]
            or report["status"] != "passed"
        ):
            raise ValueError("review and verification do not bind this source/report")
    replay_results = {}
    if replay:
        from legacylift.modernization.study import evaluate_source

        # The source is already approved and fixed. Results cannot feed a repair loop.
        result = json.loads((home / "runs" / run_id / "result.json").read_text())
        for split in ("guidance", "held_out"):
            evaluation = evaluate_source(source, home, workflow=result["workflow"], split=split)
            replay_results[split] = {
                key: evaluation[key] for key in ("status", "passed_count", "scenario_count")
            }
            if evaluation["status"] != "passed":
                raise ValueError(f"exported source failed fresh {split} Docker verification")
    if output.exists() and output.read_bytes() != first.content:
        raise ValueError("output exists with different content; use a new output filename")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(first.content)
    return {
        "status": "passed",
        "run_id": run_id,
        "repeated_exports_identical": True,
        "archive_sha256": hashlib.sha256(first.content).hexdigest(),
        "source_sha256": source_digest,
        "verification_sha256": canonical_hash(report),
        "file_count": len(names),
        "output": str(output.resolve()),
        "model_requests": 0,
        "candidate_execution": replay,
        "docker_replay": replay_results,
        "repair_feedback_allowed": False,
        "approval_modified": False,
        "security_certified": False,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path(".legacylift"))
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--replay", action="store_true", help="replay the approved export in Docker"
    )
    args = parser.parse_args()
    try:
        print(
            json.dumps(
                verify_export(args.home, args.run_id, args.output, replay=args.replay), indent=2
            )
        )
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Export verification failed: {error}\n")
