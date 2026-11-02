"""Filter EER evidence and source excerpts into a bounded provider request."""

from __future__ import annotations

import json
import re
from pathlib import Path

from legacylift.evidence.schema import EngineeringEvidenceRecord

from .models import EvidenceCondition, ReconstructionRequest

ALLOWED_PROVENANCE = {
    "source_only": {"source_ast"},
    "runtime_only": {"runtime_trace"},
    "hybrid": {"source_ast", "runtime_trace"},
}


def _has_allowed_provenance(item, provenance_by_id, condition: EvidenceCondition) -> bool:
    allowed = ALLOWED_PROVENANCE[condition]
    for provenance_id in item.provenance_ids:
        source = provenance_by_id[provenance_id]
        if source.kind in allowed:
            continue
        if source.kind == "analysis_limit":
            if condition == "source_only" and source.artifact.startswith(
                "src/legacylift/static_analysis/"
            ):
                continue
            if condition == "runtime_only" and source.artifact.startswith(
                "src/legacylift/runtime_capture/"
            ):
                continue
            if condition == "hybrid" and source.artifact.startswith(
                ("src/legacylift/static_analysis/", "src/legacylift/runtime_capture/")
            ):
                continue
        return False
    return bool(item.provenance_ids)


def _source_excerpt(
    record: EngineeringEvidenceRecord,
    source_root: Path,
    max_source_chars: int,
) -> tuple[str, bool]:
    source_records = [item for item in record.provenance if item.kind == "source_ast"]
    line_ranges: dict[str, list[tuple[int, int]]] = {}
    for item in source_records:
        match = re.search(r"(?:line|lines) (\d+)(?:-(\d+))?", item.locator)
        if match:
            start = int(match.group(1))
            end = int(match.group(2) or start)
            line_ranges.setdefault(item.artifact, []).append((start, end))

    pieces: list[str] = []
    remaining = max_source_chars
    truncated = False
    for relative_path in sorted(line_ranges):
        path = (source_root / relative_path).resolve()
        try:
            path.relative_to(source_root.resolve())
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, ValueError, UnicodeError):
            continue
        ranges = sorted(set(line_ranges[relative_path]))
        for start, end in ranges:
            excerpt = "\n".join(
                f"{number}: {lines[number - 1]}"
                for number in range(start, min(end, len(lines)) + 1)
            )
            piece = f"### {relative_path}:{start}-{end}\n{excerpt}\n"
            if len(piece) > remaining:
                piece = piece[:remaining]
                truncated = True
            if piece:
                pieces.append(piece)
                remaining -= len(piece)
            if remaining <= 0:
                return "\n".join(pieces), True
    return "\n".join(pieces), truncated


def _condition_limitations(
    record: EngineeringEvidenceRecord, condition: EvidenceCondition
) -> list[str]:
    if condition == "source_only":
        return [
            "Only source-derived evidence is included; runtime observations are omitted.",
            "The AST pass is best-effort and does not resolve dynamic dispatch or reflection.",
        ]
    if condition == "runtime_only":
        return [
            "Only captured synthetic scenarios are included; source findings are omitted.",
            "Behavior outside the executed scenarios is unresolved, and cookie values are omitted.",
        ]
    return record.limitations


def build_reconstruction_request(
    record: EngineeringEvidenceRecord,
    condition: EvidenceCondition,
    *,
    source_root: str | Path,
    max_source_chars: int = 6_000,
    max_contracts: int = 24,
    max_context_chars: int = 18_000,
) -> ReconstructionRequest:
    """Select one evidence condition and cap source excerpt and contract count."""
    if max_source_chars < 0 or max_contracts < 0 or max_context_chars < 1_000:
        raise ValueError("context bounds must be non-negative and max_context_chars at least 1000")
    provenance_by_id = {item.provenance_id: item for item in record.provenance}
    facts = [
        item.model_dump(mode="json")
        for item in record.observed_facts
        if _has_allowed_provenance(item, provenance_by_id, condition)
    ]
    inferences = [
        item.model_dump(mode="json")
        for item in record.inferences
        if _has_allowed_provenance(item, provenance_by_id, condition)
    ]
    unknowns = [
        item.model_dump(mode="json")
        for item in record.unknowns
        if _has_allowed_provenance(item, provenance_by_id, condition)
    ]
    all_contracts = [
        item.model_dump(mode="json")
        for item in record.contracts
        if _has_allowed_provenance(item, provenance_by_id, condition)
    ]
    contracts = all_contracts[:max_contracts]
    omitted_evidence_ids = [item["contract_id"] for item in all_contracts[max_contracts:]]
    source_excerpt, source_excerpt_truncated = (
        _source_excerpt(record, Path(source_root), max_source_chars)
        if condition in {"source_only", "hybrid"}
        else ("", False)
    )
    request = ReconstructionRequest(
        condition=condition,
        facts=facts,
        inferences=inferences,
        unknowns=unknowns,
        contracts=contracts,
        source_excerpt=source_excerpt,
        limitations=_condition_limitations(record, condition),
        omitted_evidence_ids=omitted_evidence_ids,
        source_excerpt_truncated=source_excerpt_truncated,
    )
    payload_budget = max_context_chars - 500
    while len(json.dumps(request.model_dump(mode="json"), sort_keys=True)) > payload_budget:
        if request.contracts:
            removed = request.contracts.pop()
            request.omitted_evidence_ids.append(removed["contract_id"])
        elif request.facts:
            removed = request.facts.pop()
            request.omitted_evidence_ids.append(removed["fact_id"])
        elif request.source_excerpt:
            request.source_excerpt = request.source_excerpt[: len(request.source_excerpt) // 2]
            request.source_excerpt_truncated = True
        elif request.inferences:
            removed = request.inferences.pop()
            request.omitted_evidence_ids.append(removed["inference_id"])
        elif request.unknowns:
            removed = request.unknowns.pop()
            request.omitted_evidence_ids.append(removed["unknown_id"])
        else:
            raise ValueError("the requested context limit is too small for the evidence metadata")
    return request
