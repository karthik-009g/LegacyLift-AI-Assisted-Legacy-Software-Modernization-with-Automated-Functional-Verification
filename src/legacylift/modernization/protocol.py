"""Code fingerprints for prospective controlled trials; no application or provider execution."""

import hashlib
from pathlib import Path

PROTOCOL_FOLDERS = ("modernization", "runtimes", "workbench")
SOURCE_SUFFIXES = {".py", ".rb", ".yml", ".yaml", ".lock"}
INPUT_FILES = (
    "study/integrity.json",
    "study/guidance.json",
    "study/fixture.sqlite3",
    "study/actors.private.json",
    "evidence/redmine.json",
    "evidence/runtime_routes.json",
)


def input_hashes(workspace: Path) -> dict[str, str]:
    for name in INPUT_FILES:
        path = workspace / name
        if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()):
            raise ValueError("controlled input escaped its workspace")
    return {
        name: hashlib.sha256((workspace / name).read_bytes()).hexdigest() for name in INPUT_FILES
    }


def code_hashes() -> dict[str, str]:
    package = Path(__file__).resolve().parents[1]
    paths = sorted(
        path
        for folder in PROTOCOL_FOLDERS
        for path in (package / folder).rglob("*")
        if path.is_file() and path.suffix in SOURCE_SUFFIXES
    )
    return {
        path.relative_to(package).as_posix(): hashlib.sha256(
            path.read_text(encoding="utf-8").encode("utf-8")
        ).hexdigest()
        for path in paths
    }
