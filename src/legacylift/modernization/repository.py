"""Import a pinned public reference without executing repository code."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import urllib.request
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from legacylift.runtimes.redmine import REDMINE_SOURCE_COMMIT

SOURCE_URL = f"https://codeload.github.com/redmine/redmine/zip/{REDMINE_SOURCE_COMMIT}"
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXPANDED_BYTES = 250 * 1024 * 1024


def native_source_path(path: Path) -> Path:
    """Use Windows extended paths for deep source trees without global policy changes."""
    if os.name != "nt":
        return path
    value = str(path.absolute())
    if value.startswith("\\\\?\\"):
        return Path(value)
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def source_manifest(root: Path) -> dict:
    root = native_source_path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("source tree must be a regular directory")
    files = []
    tree_hash = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("source tree contains a symbolic link")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        size = path.stat().st_size
        files.append({"path": relative, "size": size, "sha256": digest})
        tree_hash.update(relative.encode("utf-8") + b"\0")
        tree_hash.update(str(size).encode("ascii") + b"\0" + digest.encode("ascii") + b"\n")
    return {"file_manifest": files, "source_tree_sha256": tree_hash.hexdigest()}


def verify_source_tree(root: Path, provenance: dict) -> dict:
    actual = source_manifest(root)
    expected = provenance.get("file_manifest")
    if expected is not None:
        if actual != {
            "file_manifest": expected,
            "source_tree_sha256": provenance.get("source_tree_sha256"),
        }:
            raise ValueError("pinned source tree differs from its recorded integrity manifest")
        return provenance
    # Earlier local caches did not persist per-file hashes. Establish an honest local baseline
    # once; future runs detect any change. The original downloaded ZIP is not retained.
    return {
        **provenance,
        **actual,
        "integrity_baseline": "existing_local_cache; original archive not retained",
    }


def _write_provenance(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def extract_source(data: bytes, destination: Path) -> dict:
    """Validate the whole archive before writing; publish through an atomic rename."""
    destination = native_source_path(destination)
    if destination.exists():
        raise ValueError("source destination already exists; originals are immutable")
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("archive exceeds compressed size limit")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = archive.infolist()
        if not members or len(members) > 50_000:
            raise ValueError("invalid archive entry count")
        total = 0
        names = set()
        roots = set()
        files = []
        for item in members:
            name = item.orig_filename  # ZipInfo normalizes backslashes on Windows.
            parts = PurePosixPath(name).parts
            mode = item.external_attr >> 16
            if (
                not parts
                or name.startswith("/")
                or "\\" in name
                or ":" in name
                or ".." in parts
                or any(part.endswith((".", " ")) for part in parts)
                or any(ord(char) < 32 for char in name)
                or stat.S_ISLNK(mode)
                or any(
                    part.split(".")[0].upper()
                    in {
                        "CON",
                        "PRN",
                        "AUX",
                        "NUL",
                        *(f"COM{i}" for i in range(10)),
                        *(f"LPT{i}" for i in range(10)),
                    }
                    for part in parts
                )
            ):
                raise ValueError("unsafe source archive path or link")
            roots.add(parts[0])
            if item.is_dir():
                continue
            relative = PurePosixPath(*parts[1:])
            if len(parts) < 2 or relative.as_posix().casefold() in names:
                raise ValueError("archive must have a single root and unique file paths")
            names.add(relative.as_posix().casefold())
            if any(part.lower() in {".git", ".env", ".aws", ".ssh"} for part in parts):
                raise ValueError("credential or Git metadata path is not accepted")
            total += item.file_size
            if item.file_size > 10 * 1024 * 1024 or total > MAX_EXPANDED_BYTES:
                raise ValueError("archive exceeds expanded size limit")
            files.append((item, relative))
        if len(roots) != 1:
            raise ValueError("archive must have one root directory")
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.parent / f".import-{uuid.uuid4().hex}"
        staging.mkdir()
        try:
            for item, relative in files:
                output = staging.joinpath(*relative.parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(archive.read(item))
            manifest = source_manifest(staging)
            staging.rename(destination)
        finally:
            if staging.exists():
                if staging.is_symlink() or staging.resolve().parent != destination.parent.resolve():
                    raise ValueError("source cleanup escaped its staging parent")
                shutil.rmtree(staging)
    return {
        "archive_sha256": hashlib.sha256(data).hexdigest(),
        "files": len(files),
        "expanded_bytes": total,
        **manifest,
    }


def import_redmine(workspace: Path) -> dict:
    destination = native_source_path(workspace / "repositories" / REDMINE_SOURCE_COMMIT)
    provenance = destination.parent / f"{REDMINE_SOURCE_COMMIT}.json"
    if destination.exists():
        if not provenance.is_file():
            raise ValueError("existing source has no provenance; choose a clean workspace")
        existing = json.loads(provenance.read_text(encoding="utf-8"))
        checked = verify_source_tree(destination, existing)
        if checked is not existing:
            _write_provenance(provenance, checked)
        return {**checked, "source_directory": str(destination.absolute())}
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "LegacyLift/2"})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read(MAX_ARCHIVE_BYTES + 1)
    result = extract_source(data, destination)
    result.update(
        {
            "repository": "https://github.com/redmine/redmine",
            "ref": "4.2.10",
            "commit": REDMINE_SOURCE_COMMIT,
            "source_url": SOURCE_URL,
            "license": "GPL-2.0-or-later; retain upstream notices",
            "source_directory": str(destination.resolve()),
            "executed_on_host": False,
        }
    )
    _write_provenance(provenance, result)
    return result
