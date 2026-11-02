"""Read and write validated Engineering Evidence Records."""

from __future__ import annotations

import json
from pathlib import Path

from .schema import EngineeringEvidenceRecord


def write_eer(record: EngineeringEvidenceRecord, output_path: str | Path) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        record.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False
    )
    destination.write_text(content + "\n", encoding="utf-8")
    return destination


def load_eer(input_path: str | Path) -> EngineeringEvidenceRecord:
    return EngineeringEvidenceRecord.model_validate_json(
        Path(input_path).read_text(encoding="utf-8")
    )


def write_eer_schema(output_path: str | Path) -> Path:
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        EngineeringEvidenceRecord.model_json_schema(),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    destination.write_text(content + "\n", encoding="utf-8")
    return destination
