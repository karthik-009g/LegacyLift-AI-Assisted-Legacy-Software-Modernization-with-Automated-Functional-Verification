"""Build/check an isolated security proposal without changing the frozen study runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from legacylift.modernization.mutations import run_candidate_code_mutation_campaign
from legacylift.modernization.protocol import code_hashes
from legacylift.modernization.security_assessment import assess_runtime_isolation
from legacylift.runtimes.images import build_image

BASE_REFERENCE = "legacylift-target-base:afae956d324f60e0bfa6"
BASE_IMAGE_ID = "sha256:e98ac3b6930f430750670a2d95d4eb17a98f43b614abd6050fc3605835b746b7"
ZLIB_VERSION = "1:1.3.dfsg+really1.3.1-1+deb13u1"
PROPOSALS = Path(".legacylift/security/proposals")

BOOTSTRAP_CLEANUP = """import sysconfig
from pathlib import Path

stdlib = Path(sysconfig.get_path("stdlib"))
if stdlib != Path("/usr/local/lib/python3.14"):
    raise RuntimeError("unexpected standard-library directory; refusing cleanup")
bundled = stdlib / "ensurepip" / "_bundled"
if bundled.is_symlink():
    raise RuntimeError("unexpected bootstrap directory link")
for wheel in bundled.glob("*.whl"):
    if wheel.is_symlink() or wheel.parent != bundled:
        raise RuntimeError("unexpected bootstrap archive path")
    wheel.unlink()
"""

INVENTORY_CODE = """import importlib.metadata, importlib.util, json, pathlib, subprocess, sys, zlib
print(json.dumps({
    "python": sys.version.split()[0],
    "zlib_package": subprocess.check_output(
        ["dpkg-query", "-W", "-f=${Version}", "zlib1g"], text=True).strip(),
    "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION,
    "pip_importable": importlib.util.find_spec("pip") is not None,
    "bundled_installer_wheels": sorted(p.name for p in
        pathlib.Path("/usr/local/lib/python3.14/ensurepip/_bundled").glob("*.whl")),
    "distributions": sorted([{"name": d.metadata["Name"], "version": d.version}
        for d in importlib.metadata.distributions()], key=lambda d: d["name"].lower()),
}))
"""


def docker(*arguments: str) -> str:
    return subprocess.run(
        ["docker", *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=True,
    ).stdout


def inspect_image(reference: str, expected_id: str | None = None) -> dict:
    inspected = json.loads(docker("image", "inspect", reference))[0]
    if expected_id is not None and inspected["Id"] != expected_id:
        raise ValueError("image ID differs from the recorded hardening input")
    return inspected


def inventory(reference: str) -> dict:
    name = "legacylift-hardening-" + uuid.uuid4().hex[:12]
    try:
        return json.loads(
            docker(
                "run",
                "--rm",
                "--pull=never",
                "--name",
                name,
                "--label",
                "io.legacylift.role=hardening-assessment",
                "--network=none",
                "--read-only",
                "--user=999:999",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--memory=128m",
                "--cpus=1",
                "--pids-limit=32",
                "--entrypoint",
                "python",
                reference,
                "-I",
                "-c",
                INVENTORY_CODE,
            )
        )
    finally:
        subprocess.run(
            ["docker", "rm", "--force", name], capture_output=True, timeout=15, check=False
        )


def write_report(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def build_proposal(base_reference: str, expected_id: str, zlib_version: str) -> dict:
    # Check untrusted CLI values before creating directories, tagging or building.
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_id):
        raise ValueError("expected image ID must be a full SHA-256 ID")
    if not re.fullmatch(r"[0-9][0-9A-Za-z.+:~_-]*", zlib_version):
        raise ValueError("zlib version must be an exact Debian package version")
    inspect_image(base_reference, expected_id)
    proposal_id = uuid.uuid4().hex
    directory = PROPOSALS / proposal_id
    directory.mkdir(parents=True, exist_ok=False)
    frozen_code = code_hashes()
    base_alias = "legacylift-hardening-input:" + expected_id.removeprefix("sha256:")
    dockerfile = (
        f"FROM {base_alias}\nUSER 0\n"
        "RUN apt-get update && apt-get install --yes --no-install-recommends --only-upgrade "
        f"zlib1g={zlib_version} && rm -rf /var/lib/apt/lists/*\n"
        "RUN python -m pip uninstall --yes pip\n"
        "COPY bootstrap_cleanup.py /bootstrap_cleanup.py\n"
        "RUN python -I /bootstrap_cleanup.py && rm /bootstrap_cleanup.py\n"
        "USER 999:999\n"
    )
    (directory / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    (directory / "bootstrap_cleanup.py").write_text(BOOTSTRAP_CLEANUP, encoding="utf-8")
    report = {
        "proposal_id": proposal_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "building",
        "adopted": False,
        "base_reference": base_reference,
        "base_image_id": expected_id,
        "requested_zlib_version": zlib_version,
        "zlib_advisory_source": "https://www.debian.org/security/2026/dsa-6613",
        "dockerfile_sha256": hashlib.sha256(dockerfile.encode()).hexdigest(),
        "cleanup_sha256": hashlib.sha256(BOOTSTRAP_CLEANUP.encode()).hexdigest(),
        "frozen_code_sha256": frozen_code,
        "model_requests": 0,
        "held_out_observations_read": False,
        "limitations": [
            "Standalone proposal, not the runtime of the fixed model study.",
            "Signed APT metadata and exact package version; no Debian snapshot mirror.",
            "Removes pip/bootstrap archives after dependencies; no runtime package installs.",
            "Advisory re-scan and functional checks are separate from image construction.",
        ],
    }
    path = directory / "proposal.json"
    write_report(path, report)
    print(json.dumps({"proposal_id": proposal_id, "status": "building"}), flush=True)
    try:
        report["before"] = inventory(base_reference)
        docker("image", "tag", expected_id, base_alias)
        image = build_image(
            dockerfile,
            {"bootstrap_cleanup.py": BOOTSTRAP_CLEANUP.encode()},
            prefix="target-hardening",
            install_dependencies=True,
        )
        inspected = inspect_image(image)
        after = inventory(image)
        if after["zlib_package"] != zlib_version or after["pip_importable"]:
            raise ValueError("constructed image does not have the requested package state")
        if after["bundled_installer_wheels"]:
            raise ValueError("unused bootstrap archives remain")
        if code_hashes() != frozen_code:
            raise ValueError("fingerprinted project code changed during independent image build")
        report.update(
            status="built_unadopted", image_reference=image, image_id=inspected["Id"], after=after
        )
    except Exception as error:
        report.update(
            status="build_failed", error_type=type(error).__name__, detail=str(error)[-1800:]
        )
        write_report(path, report)
        raise
    write_report(path, report)
    return report


def verify_proposal(proposal_id: str, workspace: Path) -> dict:
    if not re.fullmatch(r"[0-9a-f]{32}", proposal_id):
        raise ValueError("invalid proposal ID")
    directory = PROPOSALS / proposal_id
    path = directory / "verification.json"
    if path.exists():
        raise ValueError("verification is already recorded; preserve the existing attempt")
    proposal = json.loads((directory / "proposal.json").read_text(encoding="utf-8"))
    if proposal["status"] != "built_unadopted":
        raise ValueError("proposal did not complete construction")
    image = proposal["image_reference"]
    inspect_image(image, proposal["image_id"])
    frozen_code = code_hashes()
    if frozen_code != proposal["frozen_code_sha256"]:
        raise ValueError("project code changed since the proposal build")
    # This override is confined to this developer process. The study runs in a
    # different process and its source/constants/manifest are never modified.
    with patch("legacylift.runtimes.python_target.target_base", return_value=image):
        isolation = assess_runtime_isolation()
        mutations = run_candidate_code_mutation_campaign(
            workspace, directory / "candidate-mutations.json"
        )
    write_report(directory / "isolation.json", isolation)
    report = {
        "proposal_id": proposal_id,
        "image_reference": image,
        "image_id": proposal["image_id"],
        "status": "passed" if isolation["status"] == mutations["status"] == "passed" else "failed",
        "adopted": False,
        "certified_secure": False,
        "isolation_checks_passed": sum(isolation["checks"].values()),
        "isolation_checks": len(isolation["checks"]),
        "baseline_passed_count": mutations["baseline_passed_count"],
        "baseline_scenario_count": mutations["baseline_scenario_count"],
        "detected_mutations": mutations["detected_count"],
        "mutation_count": mutations["mutation_count"],
        "model_requests": 0,
        "held_out_observations_read": False,
        "frozen_code_unchanged": code_hashes() == frozen_code,
        "limitations": [
            "Engineered four-case guidance fixture; no model success or general equivalence claim.",
            "Advisory re-scan/triage remains required; this result does not adopt an image.",
        ],
    }
    if not report["frozen_code_unchanged"]:
        report["status"] = "failed"
    write_report(path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    build = commands.add_parser("build")
    build.add_argument("--base-reference", default=BASE_REFERENCE)
    build.add_argument("--expected-id", default=BASE_IMAGE_ID)
    build.add_argument("--zlib-version", default=ZLIB_VERSION)
    verify = commands.add_parser("verify")
    verify.add_argument("proposal_id")
    verify.add_argument("--home", type=Path, default=Path(".legacylift"))
    arguments = parser.parse_args()
    if arguments.action == "build":
        result = build_proposal(
            arguments.base_reference, arguments.expected_id, arguments.zlib_version
        )
    else:
        result = verify_proposal(arguments.proposal_id, arguments.home)
    print(json.dumps({key: result[key] for key in ("proposal_id", "status", "adopted")}))
    return 0 if result["status"] in {"built_unadopted", "passed"} else 1


if __name__ == "__main__":
    sys.exit(main())
