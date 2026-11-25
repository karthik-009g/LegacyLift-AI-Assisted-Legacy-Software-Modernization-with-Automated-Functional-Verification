from __future__ import annotations

import ast
import hashlib
import shutil
from pathlib import Path

import pytest

from legacylift.evaluation.compatibility import RAW_CANDIDATE_HASHES, prepare_compatibility_repairs
from legacylift.reconstruction.models import ReconstructionProposal

RAW_PROPOSALS = Path(__file__).parents[1] / "artifacts" / "experiments" / "raw_proposals"


def test_compatibility_recipe_is_reproducible_and_preserves_raw_drafts(tmp_path):
    originals = {path.name: path.read_bytes() for path in RAW_PROPOSALS.glob("*.json")}
    first = tmp_path / "first"
    second = tmp_path / "second"

    manifest = prepare_compatibility_repairs(RAW_PROPOSALS, first)
    prepare_compatibility_repairs(RAW_PROPOSALS, second)

    assert manifest["candidate_code_executed"] is False
    assert manifest["human_correction_effort"]["status"] == "not_measured"
    for condition, raw_hash in RAW_CANDIDATE_HASHES.items():
        name = f"{condition}.json"
        assert (RAW_PROPOSALS / name).read_bytes() == originals[name]
        assert (first / name).read_bytes() == (second / name).read_bytes()
        checked_in = RAW_PROPOSALS.parent / "compatibility_repaired" / name
        assert (first / name).read_bytes() == checked_in.read_bytes()
        repaired = ReconstructionProposal.model_validate_json((first / name).read_text("utf-8"))
        assert repaired.derivation.parent_candidate_sha256 == raw_hash
        assert manifest["conditions"][condition]["diff"]
        assert hashlib.sha256(repaired.proposed_code.encode()).hexdigest() != raw_hash
        ast.parse(repaired.proposed_code)
    assert (first / "repair_manifest.json").read_bytes() == (
        second / "repair_manifest.json"
    ).read_bytes()


def test_compatibility_recipe_rejects_changed_input_before_writing_any_output(tmp_path):
    source = tmp_path / "raw"
    shutil.copytree(RAW_PROPOSALS, source)
    candidate_path = source / "hybrid.json"
    candidate = ReconstructionProposal.model_validate_json(candidate_path.read_text("utf-8"))
    candidate = candidate.model_copy(
        update={"proposed_code": candidate.proposed_code + "\n# changed"}
    )
    candidate_path.write_text(candidate.model_dump_json(), encoding="utf-8")
    output = tmp_path / "repaired"

    with pytest.raises(ValueError, match="original saved draft"):
        prepare_compatibility_repairs(source, output)

    assert not output.exists()


def test_compatibility_recipe_refuses_to_overwrite_raw_directory():
    with pytest.raises(ValueError, match="saved separately"):
        prepare_compatibility_repairs(RAW_PROPOSALS, RAW_PROPOSALS)
