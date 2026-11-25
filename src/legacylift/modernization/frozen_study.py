"""Seal reference artifacts once; guidance replay never opens the combined oracle."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contracts import canonical_hash, contract_manifest, scenarios

SEAL_VERSION = "redmine-frozen-study-1"
SEALED_INPUTS = ("guidance.json", "fixture.sqlite3", "actors.private.json")


def _path(workspace: Path, name: str) -> Path:
    directory = workspace / "study"
    path = directory / name
    if (
        directory.is_symlink()
        or path.is_symlink()
        or not path.resolve().is_relative_to(workspace.resolve())
    ):
        raise ValueError("frozen study artifact escaped its workspace")
    return path


def _read(workspace: Path, name: str) -> tuple[dict, str]:
    raw = _path(workspace, name).read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("frozen study artifact must be an object")
    return value, hashlib.sha256(raw).hexdigest()


def _validate_cases(artifact: dict, *, guidance_only: bool) -> None:
    if artifact.get("contract") != contract_manifest():
        raise ValueError("scenario manifest differs from frozen study")
    declared = [case for case in scenarios() if not guidance_only or case["split"] == "guidance"]
    cases = artifact.get("scenarios")
    if not isinstance(cases, list) or len(cases) != len(declared):
        raise ValueError("frozen study scenario set differs from contract")
    for expected, case in zip(declared, cases, strict=True):
        if not isinstance(case, dict) or any(
            case.get(key) != value for key, value in expected.items()
        ):
            raise ValueError("frozen study scenario identity or requests differ from contract")
        steps = case.get("steps")
        if not isinstance(steps, list) or len(steps) != len(expected["requests"]):
            raise ValueError("frozen study step count differs from contract")
        if any(
            not isinstance(step, dict) or step.get("request") != request
            for step, request in zip(steps, expected["requests"], strict=True)
        ):
            raise ValueError("frozen study captured request differs from contract")


def _validate_seal(workspace: Path) -> dict:
    try:
        seal, _ = _read(workspace, "integrity.json")
    except FileNotFoundError as error:
        raise ValueError("frozen study is unsealed; run v2 seal-study before evaluation") from error
    payload = {key: value for key, value in seal.items() if key != "seal_sha256"}
    if (
        seal.get("version") != SEAL_VERSION
        or seal.get("contract") != contract_manifest()
        or canonical_hash(payload) != seal.get("seal_sha256")
        or set(seal.get("inputs", {})) != set(SEALED_INPUTS)
    ):
        raise ValueError("frozen study integrity manifest differs")
    for name in SEALED_INPUTS:
        actual = hashlib.sha256(_path(workspace, name).read_bytes()).hexdigest()
        if actual != seal["inputs"][name]:
            raise ValueError(f"frozen study input checksum differs: {name}")
    return seal


def seal_study(workspace: Path) -> dict:
    """Trusted setup reads the oracle once, without disclosing its observations."""
    oracle, oracle_file_hash = _read(workspace, "oracle.json")
    guidance, guidance_file_hash = _read(workspace, "guidance.json")
    _validate_cases(oracle, guidance_only=False)
    _validate_cases(guidance, guidance_only=True)
    digest = canonical_hash(oracle["scenarios"])
    if oracle.get("oracle_sha256") != digest or guidance.get("oracle_sha256") != digest:
        raise ValueError("frozen oracle checksum differs")
    expected = [case for case in oracle["scenarios"] if case["split"] == "guidance"]
    if guidance["scenarios"] != expected:
        raise ValueError("guidance observations differ from frozen reference")
    seal = {
        "version": SEAL_VERSION,
        "contract": contract_manifest(),
        "parent_oracle_sha256": digest,
        "oracle_file_sha256": oracle_file_hash,
        "inputs": {
            name: guidance_file_hash
            if name == "guidance.json"
            else hashlib.sha256(_path(workspace, name).read_bytes()).hexdigest()
            for name in SEALED_INPUTS
        },
    }
    seal["seal_sha256"] = canonical_hash(seal)
    destination = _path(workspace, "integrity.json")
    if destination.exists():
        existing = _validate_seal(workspace)
        if existing != seal:
            raise ValueError("frozen study seal is immutable; version a new workspace")
        return existing
    with destination.open("x", encoding="utf-8", newline="\n") as output:
        output.write(json.dumps(seal, sort_keys=True, indent=2) + "\n")
    return seal


def evaluation_artifact(workspace: Path, split: str) -> tuple[dict, dict]:
    if split not in {"guidance", "held_out", "all"}:
        raise ValueError("invalid evaluation split")
    seal = _validate_seal(workspace)
    if split == "guidance":
        artifact, file_hash = _read(workspace, "guidance.json")
        if file_hash != seal["inputs"]["guidance.json"]:
            raise ValueError("frozen study input checksum differs: guidance.json")
        _validate_cases(artifact, guidance_only=True)
    else:
        artifact, file_hash = _read(workspace, "oracle.json")
        _validate_cases(artifact, guidance_only=False)
        if (
            file_hash != seal["oracle_file_sha256"]
            or canonical_hash(artifact["scenarios"]) != seal["parent_oracle_sha256"]
        ):
            raise ValueError("frozen oracle content checksum differs")
    if artifact.get("oracle_sha256") != seal["parent_oracle_sha256"]:
        raise ValueError("frozen study parent oracle checksum differs")
    return artifact, seal


def execution_inputs(workspace: Path, seal: dict) -> tuple[bytes, dict]:
    """Hash the exact buffers handed to the runtime, including changes after preflight."""
    database = _path(workspace, "fixture.sqlite3").read_bytes()
    actor_bytes = _path(workspace, "actors.private.json").read_bytes()
    for name, raw in (("fixture.sqlite3", database), ("actors.private.json", actor_bytes)):
        if hashlib.sha256(raw).hexdigest() != seal["inputs"][name]:
            raise ValueError(f"frozen study input checksum differs: {name}")
    actors = json.loads(actor_bytes)
    if not isinstance(actors, dict):
        raise ValueError("frozen actor mapping must be an object")
    return database, actors
