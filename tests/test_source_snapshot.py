import json
import subprocess
from pathlib import Path

import pytest

from legacylift.modernization.source_snapshot import create_source_snapshot, verify_source_snapshot


@pytest.mark.parametrize("secret_name", [".env", ".ENV", ".env.local"])
def test_snapshot_includes_untracked_code_and_excludes_even_tracked_credentials(
    tmp_path, secret_name
):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "module.py").write_text("value = 1\n")
    (tmp_path / secret_name).write_text("PRIVATE_MARKER=do-not-copy")
    (tmp_path / ".env.example").write_text("API_KEY=\n")
    (tmp_path / "ion").write_text("unrelated")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "-f", secret_name], check=True, capture_output=True
    )
    report = create_source_snapshot(tmp_path)
    assert set(report["files"]) == {"module.py", ".env.example"}
    assert report["verification_state"] == "snapshot_only"
    assert report["generation_requests"] == 0
    assert (tmp_path / secret_name).read_text() == "PRIVATE_MARKER=do-not-copy"
    manifest = Path(report["source_directory"]).parent / "manifest.json"
    assert verify_source_snapshot(manifest)["status"] == "verified"


def test_snapshot_verification_rejects_changed_bytes_and_traversal(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "code.py").write_text("value = 1\n")
    report = create_source_snapshot(tmp_path)
    source = Path(report["source_directory"])
    manifest = source.parent / "manifest.json"
    (source / "code.py").write_text("value = 2\n")
    with pytest.raises(ValueError, match="checksum differs"):
        verify_source_snapshot(manifest)
    data = json.loads(manifest.read_text())
    data["files"] = {"../code.py": "a" * 64}
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="unsafe path"):
        verify_source_snapshot(manifest)


def test_snapshot_rejects_windows_separator_escape_before_copy(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from legacylift.modernization import source_snapshot

    monkeypatch.setattr(
        source_snapshot.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout=b"folder\\..\\.env\0"),
    )
    with pytest.raises(ValueError, match="unsafe path"):
        create_source_snapshot(tmp_path)
    assert not (tmp_path / ".legacylift").exists()
