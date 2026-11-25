"""Run the trusted AST policy under the target interpreter without importing candidate code."""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid

from .images import build_image
from .python_target import target_base

SCANNER = b"""import json, sys
sys.path.insert(0, "/static-review")
from review_policy import review_source
source = sys.stdin.buffer.read(200001).decode("utf-8")
if len(source.encode("utf-8")) > 200000:
    raise ValueError("source exceeds static review limit")
report = review_source(source)
report["parser_runtime"] = "python-target-container"
report["parser_python_version"] = sys.version.split()[0]
print(json.dumps(report))
"""


def run_target_static_review(source: str, policy: bytes) -> dict:
    if len(source.encode("utf-8")) > 200_000:
        raise ValueError("source exceeds static review limit")
    image = build_image(
        f"FROM {target_base()}\nCOPY review_policy.py scanner.py /static-review/\n",
        {"review_policy.py": policy, "scanner.py": SCANNER},
        prefix="static-review",
    )
    name = "legacylift-static-" + uuid.uuid4().hex[:12]
    try:
        completed = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--label=io.legacylift.role=static-review",
                "--pull=never",
                "--network=none",
                "--read-only",
                "--user",
                "999:999",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=32",
                "--memory=128m",
                "--cpus=0.5",
                "-i",
                image,
                "python",
                "-I",
                "/static-review/scanner.py",
            ],
            input=source.encode("utf-8"),
            capture_output=True,
            timeout=45,
            check=False,
        )
    finally:
        subprocess.run(
            ["docker", "rm", "--force", name], capture_output=True, timeout=15, check=False
        )
    if completed.returncode:
        raise RuntimeError("Target static reviewer failed; candidate source was not executed")
    result = json.loads(completed.stdout)
    if (
        result.get("status") not in {"blocked", "static_review_passed"}
        or not isinstance(result.get("findings"), list)
        or result.get("parser_runtime") != "python-target-container"
        or not str(result.get("parser_python_version", "")).startswith("3.14.")
    ):
        raise RuntimeError("Target static reviewer returned invalid provenance")
    result["source_utf8_sha256"] = hashlib.sha256(source.encode("utf-8")).hexdigest()
    result["policy_sha256"] = hashlib.sha256(policy).hexdigest()
    return result
