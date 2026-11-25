"""Verify installed assets, reference replay, Python and browser checks in a snapshot.

Requires reproduce_install.py to have passed for this manifest. No model calls.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reproduce_install import PROJECT, clean_environment, verify_source_snapshot  # noqa: E402


def reproduce_checks(manifest_path: Path) -> dict:
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_relative_to(PROJECT / ".legacylift" / "reproductions"):
        raise ValueError("reproduction must remain inside the workspace")
    verified = verify_source_snapshot(manifest_path)
    run = manifest_path.parent
    source = run / "source"
    environment = source / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    installed = json.loads((run / "install-verification.json").read_text(encoding="utf-8"))
    if installed["status"] != "passed" or installed["snapshot"] != verified:
        raise ValueError("a passing installation for the exact snapshot is required")
    report_path = run / "checks-verification.json"
    if report_path.exists():
        raise ValueError("preserve the recorded check attempt; use a fresh snapshot")
    env = clean_environment()
    report = {
        "kind": "local_source_snapshot_checks",
        "snapshot": verified,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "generation_requests": 0,
        "stages": [],
        "status": "running",
        "security_verdict": "not_assessed",
        "limitations": [
            "Same Windows host and cached Docker/browser binaries.",
            "Uncommitted source snapshot, not a published checkout.",
            "Synthetic browser tests are not model migration evidence.",
        ],
    }

    def save():
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    def stage(name, command, *, cwd=source, extra_env=None):
        started = time.monotonic()
        row = {"name": name, "command": command, "status": "running", "log": name + ".log"}
        report["stages"].append(row)
        save()
        print(name, flush=True)
        try:
            with (run / row["log"]).open("wb") as log:
                result = subprocess.run(
                    command,
                    cwd=cwd,
                    env={**env, **(extra_env or {})},
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=900,
                    check=False,
                )
            row.update(
                status="passed" if result.returncode == 0 else "failed", exit_code=result.returncode
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            row.update(status="failed", error_type=type(error).__name__)
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if row["status"] != "passed":
            report["status"] = "failed"
            save()
            raise RuntimeError(f"Reproduction failed at {name}; inspect its saved log")
        save()

    asset_code = """import hashlib,json,sys; from pathlib import Path; import legacylift
run=Path(sys.argv[1]); root=Path(legacylift.__file__).resolve().parent
assert root.is_relative_to((run/'source/.venv').resolve())
manifest=json.loads((run/'manifest.json').read_text(encoding='utf-8')); count=0
for name,digest in manifest['files'].items():
 if name.startswith('src/legacylift/'):
  installed=root/name.removeprefix('src/legacylift/')
  assert hashlib.sha256(installed.read_bytes()).hexdigest()==digest,name
  count+=1
print(json.dumps({'verified_package_files':count,'python':sys.version.split()[0]}))
"""
    stage("installed-assets", [str(python), "-I", "-c", asset_code, str(run)], cwd=run)
    reference_code = """import json
from pathlib import Path
from legacylift.modernization.study import prepare_study
result=prepare_study(Path('.legacylift'), checkpoint=lambda m,p: print(m,flush=True))
keys=('status','contract','oracle_sha256','runtime_route_count')
summary={k:result[k] for k in keys if k in result}
Path('../reference-verification.json').write_text(json.dumps(summary,indent=2)+'\\n',encoding='utf-8')
"""
    stage("reference-prepare", [str(python), "-I", "-c", reference_code])
    reference = json.loads((run / "reference-verification.json").read_text(encoding="utf-8"))
    previous_seal = PROJECT / ".legacylift/study/integrity.json"
    if previous_seal.exists():
        prior = json.loads(previous_seal.read_text(encoding="utf-8"))
        report["matches_saved_reference"] = (
            reference["oracle_sha256"] == prior["parent_oracle_sha256"]
        )
        if not report["matches_saved_reference"]:
            report["status"] = "failed"
            save()
            raise ValueError("fresh reference differs from the saved frozen reference")
    report["reference"] = reference
    stage(
        "build-v1-evaluator",
        [
            "docker",
            "build",
            "--file",
            "Dockerfile.evaluation",
            "--tag",
            "legacylift-evaluation:py311",
            ".",
        ],
    )
    gates = {
        key: "1"
        for key in (
            "LEGACYLIFT_DOCKER_SMOKE",
            "LEGACYLIFT_V2_DOCKER_SMOKE",
            "LEGACYLIFT_RUNTIME_MUTATION_SMOKE",
            "LEGACYLIFT_CODE_MUTATION_SMOKE",
        )
    }
    stage("python-tests", [str(python), "-I", "-m", "pytest", "-q"], extra_env=gates)
    output = (run / "python-tests.log").read_text(encoding="utf-8", errors="replace")
    count = re.search(r"(\d+) passed", output)
    report["python_passed"] = int(count.group(1)) if count else None
    report["python_skipped"] = sum(int(n) for n in re.findall(r"(\d+) skipped", output))
    stage("python-lint", [str(python), "-I", "-m", "ruff", "check", "src", "tests", "scripts"])
    stage(
        "python-format",
        [str(python), "-I", "-m", "ruff", "format", "--check", "src", "tests", "scripts"],
    )
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm:
        report["status"] = "failed"
        save()
        raise ValueError("npm executable unavailable")
    stage("web-install", [npm, "ci", "--no-audit", "--no-fund"], cwd=source / "web")
    stage("web-review-export", [npm, "run", "test:e2e:review"], cwd=source / "web")
    report["snapshot_after_checks"] = verify_source_snapshot(manifest_path)
    report["status"] = "passed"
    save()
    return report


if __name__ == "__main__":
    result = reproduce_checks(Path(sys.argv[1]))
    print(
        json.dumps(
            {
                "status": result["status"],
                "python_passed": result["python_passed"],
                "python_skipped": result["python_skipped"],
            }
        )
    )
