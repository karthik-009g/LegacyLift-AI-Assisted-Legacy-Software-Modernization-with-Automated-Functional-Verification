"""Query release-specific PyPI advisories for exact pins without installing packages."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


def audit_locks(paths: list[Path], *, transport=None) -> dict:
    packages = {}
    locks = {}
    # Validate every input before any request. Do not resolve URLs, ranges or other indexes.
    for path in paths:
        raw = path.read_bytes()
        locks[path.as_posix()] = hashlib.sha256(raw).hexdigest()
        for line in raw.decode("utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            requirement = Requirement(line)
            specs = list(requirement.specifier)
            if (
                requirement.url
                or len(specs) != 1
                or specs[0].operator != "=="
                or "*" in specs[0].version
            ):
                raise ValueError("advisory audit requires exact public package/version pins")
            name, version = canonicalize_name(requirement.name), str(Version(specs[0].version))
            packages.setdefault((name, version), []).append(path.as_posix())
    checked, findings, errors = [], [], []
    with httpx.Client(transport=transport, timeout=15, trust_env=False) as client:
        for (name, version), origins in sorted(packages.items()):
            url = f"https://pypi.org/pypi/{name}/{version}/json"
            try:
                response = client.get(url)
                response.raise_for_status()
                payload = response.json()
                if (
                    canonicalize_name(payload["info"]["name"]) != name
                    or Version(payload["info"]["version"]) != Version(version)
                    or not isinstance(payload.get("vulnerabilities"), list)
                    or any(not isinstance(item, dict) for item in payload["vulnerabilities"])
                ):
                    raise ValueError("release metadata does not match the audited pin")
                advisories = []
                for advisory in payload["vulnerabilities"]:
                    if advisory.get("withdrawn"):
                        continue
                    if not isinstance(advisory.get("id"), str):
                        raise ValueError("invalid advisory metadata")
                    advisories.append(
                        {
                            "name": name,
                            "version": version,
                            "locks": origins,
                            "id": advisory["id"],
                            "aliases": advisory.get("aliases", []),
                            "fixed_in": advisory.get("fixed_in", []),
                            "advisory_url": advisory.get("link"),
                            "release_metadata_url": url,
                        }
                    )
                checked.append({"name": name, "version": version, "locks": origins})
                findings.extend(advisories)
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                errors.append(
                    {"name": name, "version": version, "error_type": type(error).__name__}
                )
    return {
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "PyPI release JSON vulnerabilities array",
        "source_documentation": "https://docs.pypi.org/api/json/",
        "status": "incomplete" if errors else "findings" if findings else "no_known_advisories",
        "certified_secure": False,
        "lock_sha256": locks,
        "requested_package_versions": len(packages),
        "checked_package_versions": len(checked),
        "checked": checked,
        "findings": findings,
        "errors": errors,
        "limitations": [
            "Known published Python advisories only; absence is not proof of safety.",
            "Queries all pins, including development and platform-specific dependencies.",
            "Does not inspect source, installed bytes, OS packages or malicious packages.",
            "No dependency resolution, installation, account credentials or model request.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "locks",
        nargs="*",
        type=Path,
        default=[
            Path("requirements.lock"),
            Path("requirements-build.lock"),
            Path("src/legacylift/runtimes/assets/target-requirements.lock"),
        ],
    )
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/v2/python_dependency_advisories.json")
    )
    arguments = parser.parse_args()
    report = audit_locks(arguments.locks)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "checked": report["checked_package_versions"],
                "findings": len(report["findings"]),
                "errors": len(report["errors"]),
                "report": str(arguments.output),
            }
        )
    )
    return 2 if report["errors"] else 1 if report["findings"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
