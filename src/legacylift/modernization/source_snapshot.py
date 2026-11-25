"""Snapshot local project source while excluding private configuration and artifacts."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import uuid
from pathlib import Path, PurePosixPath

EXCLUDED = {".git", ".legacylift", ".venv", "node_modules", ".codex", ".agents", ".aws"}


def _relative(name: str) -> PurePosixPath:
    relative = PurePosixPath(name)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or ":" in name
        or "\\" in name
        or relative.as_posix() != name
        or not relative.parts
    ):
        raise ValueError("snapshot contains an unsafe path")
    return relative


def _included(relative: PurePosixPath) -> bool:
    parts = tuple(part.casefold() for part in relative.parts)
    return (
        parts[0] != "ion"
        and not any(part in EXCLUDED for part in parts)
        and not any(part.startswith(".env") and part != ".env.example" for part in parts)
    )


def create_source_snapshot(root: Path) -> dict:
    root = root.resolve()
    listing = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={root.as_posix()}",
            "ls-files",
            "-co",
            "--exclude-standard",
            "-z",
        ],
        cwd=root,
        capture_output=True,
        check=True,
        timeout=30,
    )
    selected = []
    for raw in sorted(set(listing.stdout.split(b"\0")) - {b""}):
        name = raw.decode("utf-8")
        relative = _relative(name)
        if not _included(relative):
            continue
        source = root.joinpath(*relative.parts)
        if source.is_symlink() or not source.resolve().is_relative_to(root):
            raise ValueError("source file escaped workspace or is a symbolic link")
        if source.is_file():
            selected.append((relative, source))
    if not selected:
        raise ValueError("no source files selected")
    base = root / ".legacylift" / "reproductions"
    if not base.resolve().is_relative_to(root):
        raise ValueError("snapshot destination escaped workspace")
    directory = base / uuid.uuid4().hex
    target = directory / "source"
    target.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for relative, source in selected:
        destination = target.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        if digest != hashlib.sha256(source.read_bytes()).hexdigest():
            raise ValueError("source changed during snapshot")
        hashes[relative.as_posix()] = digest
    manifest = {
        "version": 1,
        "kind": "local_uncommitted_source_snapshot",
        "source_directory": str(target),
        "files": hashes,
        "file_count": len(hashes),
        "generation_requests": 0,
        "verification_state": "snapshot_only",
        "limitations": [
            "Not a published clean Git checkout.",
            "Fresh dependencies and runtime verification have not run.",
        ],
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def verify_source_snapshot(manifest_path: Path) -> dict:
    """Verify exact listed bytes before using the snapshot; never execute its contents."""
    if manifest_path.is_symlink():
        raise ValueError("snapshot manifest must not be a symbolic link")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("version", 1) != 1:
        raise ValueError("unsupported snapshot manifest")
    source = manifest_path.parent / "source"
    if source.is_symlink() or Path(manifest["source_directory"]).resolve() != source.resolve():
        raise ValueError("snapshot source directory differs from its manifest location")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files or len(files) != manifest.get("file_count"):
        raise ValueError("snapshot file inventory differs")
    for name, digest in files.items():
        relative = _relative(name)
        if not _included(relative):
            raise ValueError("snapshot inventory contains private or local files")
        path = source.joinpath(*relative.parts)
        if path.is_symlink() or not path.resolve().is_relative_to(source.resolve()):
            raise ValueError("snapshot file escaped its source directory")
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"snapshot checksum differs: {name}")
    if (source / ".env").exists():
        raise ValueError("snapshot contains local provider configuration")
    return {
        "status": "verified",
        "file_count": len(files),
        "source_inventory_sha256": hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "kind": manifest["kind"],
        "runtime_verification": "not_performed",
    }
