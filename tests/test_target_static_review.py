"""Target-language grammar checks parse candidate text without executing it."""

import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from legacylift.modernization import security
from legacylift.runtimes import static_review

FUTURE_SOURCE = (
    'from fastapi import FastAPI\napp = FastAPI()\ndef value(row):\n    return f"{row["id"]}"\n'
)


def test_syntax_review_keeps_parser_reason_and_position_without_source_text():
    report = security.review_source("app.py line 1: import os\n")
    finding = report["findings"][0]
    assert report["status"] == "blocked" and finding["rule"] == "invalid_python"
    assert finding["line"] == 1 and finding["offset"] > 0
    assert finding["message"]
    assert "import os" not in json.dumps(report)


@pytest.mark.parametrize(
    "fragment",
    [
        "runner = eval\nrunner('1 + 1')\n",
        "loader = __import__\nloader('subprocess')\n",
        "from builtins import eval as runner\nrunner('1 + 1')\n",
        "from os import system as runner\nrunner('true')\n",
        "import os\nrunner = os.system\nrunner('true')\n",
        "import os\ngetattr(os, 'system')('true')\n",
    ],
)
def test_policy_blocks_capability_references_before_aliasing_or_reflection(fragment):
    source = "from fastapi import FastAPI\napp = FastAPI()\n" + fragment
    report = security.review_source(source)
    assert report["status"] == "blocked"
    assert "prohibited_capability_reference" in {item["rule"] for item in report["findings"]}
    assert not security.approval_review_passes(source, [])


def test_policy_keeps_ordinary_callbacks_and_attribute_inspection():
    source = (
        "from fastapi import FastAPI\napp = FastAPI()\n"
        "callback = str\nvalue = callback(1)\n"
        "method = getattr(value, 'upper')\n"
    )
    assert security.review_source(source)["status"] == "static_review_passed"


def test_target_scanner_builds_only_trusted_policy_and_receives_utf8_candidate_as_data(monkeypatch):
    calls = []
    source = FUTURE_SOURCE + "# Résumé → 移行\n"
    policy = b"trusted policy placeholder"
    monkeypatch.setattr(static_review, "target_base", lambda: "trusted:target")

    def build(dockerfile, files, **kwargs):
        assert dockerfile.startswith("FROM trusted:target\n")
        assert files["review_policy.py"] == policy
        assert source.encode("utf-8") not in b"".join(files.values())
        return "trusted:scanner"

    monkeypatch.setattr(static_review, "build_image", build)

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {
                    "status": "static_review_passed",
                    "findings": [],
                    "parser_runtime": "python-target-container",
                    "parser_python_version": "3.14.10",
                }
            ).encode(),
        )

    monkeypatch.setattr(static_review.subprocess, "run", run)
    report = static_review.run_target_static_review(source, policy)
    command, options = calls[0]
    assert options["input"] == source.encode("utf-8")
    assert {"--network=none", "--read-only", "--cap-drop=ALL", "--memory=128m"} <= set(command)
    assert not {"--volume", "--mount", "-v", "--privileged"} & set(command)
    assert source not in " ".join(command)
    assert calls[-1][0][:3] == ["docker", "rm", "--force"]
    assert report["source_utf8_sha256"] == hashlib.sha256(source.encode("utf-8")).hexdigest()


def test_target_static_timeout_cleans_only_its_owned_container(monkeypatch):
    monkeypatch.setattr(static_review, "target_base", lambda: "trusted:target")
    monkeypatch.setattr(static_review, "build_image", lambda *args, **kwargs: "trusted:scanner")
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        if command[1] == "run":
            raise subprocess.TimeoutExpired(command, 45)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(static_review.subprocess, "run", run)
    with pytest.raises(subprocess.TimeoutExpired):
        static_review.run_target_static_review(FUTURE_SOURCE, b"policy")
    name = commands[0][commands[0].index("--name") + 1]
    assert name.startswith("legacylift-static-")
    assert commands[-1] == ["docker", "rm", "--force", name]


def test_api_approval_reuses_only_current_policy_and_source_bound_target_proof(monkeypatch):
    monkeypatch.setattr(
        security,
        "review_source",
        lambda source: {
            "status": "blocked",
            "findings": [{"rule": "invalid_python"}],
        },
    )
    proof = {
        "status": "static_review_passed",
        "policy_version": security.STATIC_POLICY_VERSION,
        "parser_runtime": "python-target-container",
        "parser_python_version": "3.14.10",
        "source_utf8_sha256": hashlib.sha256(FUTURE_SOURCE.encode()).hexdigest(),
        "policy_sha256": hashlib.sha256(Path(security.__file__).read_bytes()).hexdigest(),
    }
    assert security.approval_review_passes(FUTURE_SOURCE, [{"review": proof}])
    assert not security.approval_review_passes(FUTURE_SOURCE + "# changed\n", [{"review": proof}])
    assert not security.approval_review_passes(
        FUTURE_SOURCE, [{"review": {**proof, "policy_sha256": "0" * 64}}]
    )
    assert not security.approval_review_passes(FUTURE_SOURCE, [])
    monkeypatch.setattr(
        security,
        "review_source",
        lambda source: {
            "status": "blocked",
            "findings": [{"rule": "prohibited_capability"}],
        },
    )
    assert not security.approval_review_passes(FUTURE_SOURCE, [{"review": proof}])


@pytest.mark.skipif(
    os.environ.get("LEGACYLIFT_V2_DOCKER_SMOKE") != "1",
    reason="target AST review requires LEGACYLIFT_V2_DOCKER_SMOKE=1",
)
def test_target_ast_accepts_python314_grammar_and_keeps_capability_blocks():
    policy = Path(security.__file__).read_bytes()
    accepted = static_review.run_target_static_review(FUTURE_SOURCE, policy)
    assert accepted["status"] == "static_review_passed"
    assert accepted["parser_python_version"].startswith("3.14.")
    blocked = static_review.run_target_static_review(FUTURE_SOURCE + "import subprocess\n", policy)
    assert blocked["status"] == "blocked"
    assert "prohibited_capability" in {item["rule"] for item in blocked["findings"]}
    aliased = static_review.run_target_static_review(
        FUTURE_SOURCE + "runner = eval\nrunner('1 + 1')\n", policy
    )
    assert aliased["status"] == "blocked"
    assert "prohibited_capability_reference" in {item["rule"] for item in aliased["findings"]}
