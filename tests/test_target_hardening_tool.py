"""Developer image proposals must preserve the active study and fail before mutation."""

import importlib.util
import json
import sysconfig
from pathlib import Path

import pytest

from legacylift.runtimes import python_target

spec = importlib.util.spec_from_file_location(
    "hardening_tool", Path(__file__).parents[1] / "scripts/prepare_target_hardening.py"
)
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


@pytest.mark.parametrize(
    "expected_id,version",
    [
        ("sha256:short", "1:1.3-1"),
        ("sha256:" + "a" * 64, "1.3; invalid-command"),
        ("sha256:" + "a" * 64, "1.3\ninvalid-command"),
    ],
)
def test_invalid_build_parameters_never_reach_docker(tmp_path, monkeypatch, expected_id, version):
    monkeypatch.setattr(script, "PROPOSALS", tmp_path)
    monkeypatch.setattr(script, "docker", lambda *args: pytest.fail("invalid input reached Docker"))
    with pytest.raises(ValueError):
        script.build_proposal("ignored", expected_id, version)
    assert list(tmp_path.iterdir()) == []


def test_mismatched_base_is_rejected_before_tag_or_build(tmp_path, monkeypatch):
    calls = []

    def docker(*args):
        calls.append(args)
        return json.dumps([{"Id": "sha256:" + "b" * 64}])

    monkeypatch.setattr(script, "PROPOSALS", tmp_path)
    monkeypatch.setattr(script, "docker", docker)
    with pytest.raises(ValueError, match="image ID differs"):
        script.build_proposal("requested-base", "sha256:" + "a" * 64, "1:1.3-1")
    assert calls == [("image", "inspect", "requested-base")]
    assert list(tmp_path.iterdir()) == []


def test_cleanup_refuses_non_container_stdlib_without_deleting_files(tmp_path, monkeypatch):
    monkeypatch.setattr(sysconfig, "get_path", lambda key: str(tmp_path))
    monkeypatch.setattr(Path, "unlink", lambda *args, **kwargs: pytest.fail("unexpected deletion"))
    with pytest.raises(RuntimeError, match="unexpected standard-library"):
        exec(compile(script.BOOTSTRAP_CLEANUP, "bootstrap_cleanup.py", "exec"), {})


def test_failed_verification_restores_process_local_runtime_override(tmp_path, monkeypatch):
    proposal_id = "a" * 32
    directory = tmp_path / proposal_id
    directory.mkdir()
    (directory / "proposal.json").write_text(
        json.dumps(
            {
                "status": "built_unadopted",
                "image_reference": "proposal-image",
                "image_id": "sha256:" + "a" * 64,
                "frozen_code_sha256": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(script, "PROPOSALS", tmp_path)
    monkeypatch.setattr(script, "code_hashes", lambda: {})
    monkeypatch.setattr(script, "inspect_image", lambda *args: {})
    original = python_target.target_base

    def fail():
        assert python_target.target_base() == "proposal-image"
        raise RuntimeError("simulated diagnostic failure")

    monkeypatch.setattr(script, "assess_runtime_isolation", fail)
    with pytest.raises(RuntimeError, match="simulated diagnostic"):
        script.verify_proposal(proposal_id, tmp_path)
    assert python_target.target_base is original
    assert not (directory / "verification.json").exists()
