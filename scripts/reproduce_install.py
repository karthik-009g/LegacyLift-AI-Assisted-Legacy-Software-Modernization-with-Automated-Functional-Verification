"""Install a verified local snapshot into an independent environment; no model calls.

Run with Python 3.11+: python scripts/reproduce_install.py PATH/TO/manifest.json
The snapshot must already exist. Logs and stage results stay beside its manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import venv
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from legacylift.modernization.source_snapshot import verify_source_snapshot  # noqa: E402


def clean_environment() -> dict[str, str]:
    allowed = {
        "SYSTEMROOT",
        "WINDIR",
        "SYSTEMDRIVE",
        "COMSPEC",
        "PATH",
        "PATHEXT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "LOCALAPPDATA",
        "APPDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "PROGRAMDATA",
        "HOMEDRIVE",
        "HOMEPATH",
        "OS",
        "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE",
        "ALLUSERSPROFILE",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "NO_PROXY",
        "ALL_PROXY",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "NODE_EXTRA_CA_CERTS",
    }
    result = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    result.update(
        {
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_INDEX_URL": "https://pypi.org/simple",
            "PYTHONNOUSERSITE": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return result


def reproduce_install(manifest_path: Path) -> dict:
    manifest_path = manifest_path.resolve()
    if not manifest_path.is_relative_to(PROJECT / ".legacylift" / "reproductions"):
        raise ValueError("reproduction must remain inside this workspace's reproduction directory")
    verified = verify_source_snapshot(manifest_path)
    run = manifest_path.parent
    source = run / "source"
    # Match the repository's documented layout and browser-test interpreter lookup.
    environment = source / ".venv"
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    report_path = run / "install-verification.json"
    if report_path.exists():
        raise ValueError(
            "installation attempt already recorded; preserve it and use a fresh snapshot"
        )
    if environment.is_symlink() or not environment.resolve().is_relative_to(run):
        raise ValueError("environment escaped reproduction directory")
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    env = clean_environment()
    pristine = subprocess.run(
        [
            str(python),
            "-I",
            "-c",
            "import importlib.util,importlib.metadata,sys,site; from pathlib import Path; "
            "assert sys.prefix != sys.base_prefix and site.ENABLE_USER_SITE is False; "
            "assert Path(sys.prefix).resolve() == Path(sys.argv[1]).resolve(); "
            "assert {d.metadata['Name'].lower() for d in importlib.metadata.distributions()} "
            "<= {'pip','setuptools'}; "
            "assert importlib.util.find_spec('legacylift') is None",
            str(environment),
        ],
        cwd=run,
        env=env,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if pristine.returncode:
        raise ValueError("environment is not a fresh project installation")
    report = {
        "kind": "local_source_snapshot_installation",
        "snapshot": verified,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "generation_requests": 0,
        "stages": [],
        "status": "running",
        "limitations": ["Not a published clean Git checkout.", "Runtime replay has not run."],
    }

    def save():
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    def stage(name, arguments):
        started = time.monotonic()
        item = {"name": name, "status": "running", "log": name + ".log", "command": arguments}
        report["stages"].append(item)
        save()
        print(name, flush=True)
        try:
            with (run / item["log"]).open("wb") as log:
                result = subprocess.run(
                    arguments,
                    cwd=source,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=900,
                    check=False,
                )
            item.update(
                status="passed" if result.returncode == 0 else "failed", exit_code=result.returncode
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            item.update(status="failed", error_type=type(error).__name__)
        item["elapsed_seconds"] = round(time.monotonic() - started, 3)
        if item["status"] != "passed":
            report["status"] = "failed"
            save()
            raise RuntimeError(f"Reproduction stage failed: {name}; inspect its log")
        save()

    pip = [str(python), "-I", "-m", "pip", "--disable-pip-version-check"]
    stage("build-tools", [*pip, "install", "--no-deps", "-r", "requirements-build.lock"])
    stage("locked-dependencies", [*pip, "install", "--no-deps", "-r", "requirements.lock"])
    stage("dependency-check", [*pip, "check"])
    wheels = run / "wheels"
    stage(
        "build-wheel",
        [*pip, "wheel", "--no-deps", "--no-build-isolation", "--wheel-dir", str(wheels), "."],
    )
    candidates = list(wheels.glob("legacylift-*.whl"))
    if len(candidates) != 1:
        report["status"] = "failed"
        save()
        raise ValueError("expected exactly one built project wheel")
    stage("install-wheel", [*pip, "install", "--no-deps", str(candidates[0])])
    stage("installed-v2-cli", [str(python), "-I", "-m", "legacylift", "v2", "--help"])
    stage("installed-dependency-check", [*pip, "check"])
    try:
        report["snapshot_after_install"] = verify_source_snapshot(manifest_path)
    except (OSError, ValueError) as error:
        report["status"] = "failed"
        report["snapshot_error_type"] = type(error).__name__
        save()
        raise
    report["wheel_sha256"] = hashlib.sha256(candidates[0].read_bytes()).hexdigest()
    report["status"] = "passed"
    save()
    return report


if __name__ == "__main__":
    result = reproduce_install(Path(sys.argv[1]))
    print(json.dumps({"status": result["status"], "stages": len(result["stages"])}))
