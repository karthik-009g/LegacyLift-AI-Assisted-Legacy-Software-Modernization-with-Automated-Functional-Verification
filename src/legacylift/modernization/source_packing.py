"""Deterministic, source-location-preserving evidence packing for bounded requests."""

from __future__ import annotations

import json
import re

PACKING_VERSION = "diverse-line-windows-1"
PRIORITIES = {
    "read": ("entrypoint", "serialization", "identity", "lookup", "authorization", "visibility"),
    "create": (
        "entrypoint",
        "identity",
        "assignment",
        "validation",
        "serialization",
        "persistence",
    ),
    "update": ("entrypoint", "identity", "authorization", "transition", "audit", "assignment"),
}

# Functional rules from the pinned Redmine source, in packing priority order.
CREATE_SOURCE_ANCHORS = (
    ("app/models/issue.rb", 225, 225, "persistence"),
    ("app/views/issues/show.api.rsb", 3, 7, "serialization"),
    ("app/models/enumeration.rb", 44, 52, "assignment"),
    ("app/models/issue.rb", 583, 592, "assignment"),
)

READ_SOURCE_ANCHORS = (
    ("app/controllers/application_controller.rb", 378, 386, "lookup"),
    ("app/views/issues/show.api.rsb", 7, 7, "serialization"),
    ("app/views/issues/show.api.rsb", 28, 30, "serialization"),
    ("app/views/issues/show.api.rsb", 60, 61, "audit"),
)


def prompt_source(item: dict) -> dict:
    """Remove redundant location metadata from outbound JSON, keeping the saved context intact."""
    compact = {
        "evidence_id": item["evidence_id"],
        "sha256": item.get("sha256"),
        "lines": [item.get("start_line"), item.get("excerpt_end_line")],
        "text": item["text"],
        "truncated": item["truncated"],
    }
    # Real Ruby/template identifiers contain the path; synthetic/adapter IDs may not.
    if item.get("path") and item["path"] not in item["evidence_id"]:
        compact["path"] = item["path"]
    if item.get("selection_category"):
        compact["role"] = item["selection_category"]
    return compact


def source_bytes(items: list[dict]) -> int:
    return len(
        json.dumps(
            [prompt_source(item) for item in items], ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    )


def category(item: dict, workflow: str) -> str:
    symbol, path = item.get("symbol", ""), item.get("path", "")
    if (
        path == "app/controllers/issues_controller.rb"
        and symbol == {"read": "show", "create": "create", "update": "update"}[workflow]
    ):
        return "entrypoint"
    if item.get("kind") == "api_template_fact" or path.endswith(".api.rsb"):
        return "serialization"
    if re.search(r"current_user|api_key|authenticate|logged", symbol):
        return "identity"
    if symbol == "find_issue":
        return "lookup"
    if "visible" in symbol:
        return "visibility"
    if "validat" in symbol:
        return "validation"
    if re.search(r"authorize|permissions", symbol):
        return "authorization"
    if "journal" in path or "journal" in symbol:
        return "audit"
    if "statuses_allowed" in symbol:
        return "transition"
    if re.search(r"safe_attributes|issue_from_params", symbol):
        return "assignment"
    if re.search(r"save|default_assign", symbol):
        return "persistence"
    return "supporting"


def _line_window(item: dict, budget: int, role: str) -> dict | None:
    """Choose one contiguous run of complete lines; never insert ellipses into source."""
    lines = item["text"].splitlines(keepends=True)
    terms = {
        "entrypoint": r"format\.api|render|status|save|Unauthorized|update_issue|def ",
        "serialization": (
            r"api\.(?:id|subject|description|status|author|project|created_on|updated_on)"
        ),
        "identity": r"api_key|api_request|find_by_api_key|token|anonymous|logged",
        "lookup": r"find|visible|render_404|raise|Unauthorized",
        "authorization": r"allowed_to|authorize|deny_access|Unauthorized|logged",
        "visibility": r"allowed_to|visible|is_private|role|user",
        "assignment": r"safe_attributes|attrs|status|project|tracker|assign",
        "validation": r"errors|invalid|blank|length|subject|tracker",
        "transition": r"status|workflow|role|allowed",
        "audit": r"journal|notes|details|save|attributes|changes",
        "persistence": r"save|default|author|status|date|transaction",
        "supporting": r"return|raise|render|def ",
    }[role]
    weights = [len(re.findall(terms, line, flags=re.I)) for line in lines]
    best = None
    for start in range(len(lines)):
        text, weight = "", 0
        for end in range(start, len(lines)):
            candidate = text + lines[end]
            # JSON escaping and UTF-8 bytes count toward the real provider request cap.
            if len(json.dumps(candidate, ensure_ascii=False).encode("utf-8")) > budget:
                break
            text = candidate
            weight += weights[end]
            if not text.strip():
                continue
            score = (weight, len(text.encode("utf-8")), -start)
            if best is None or score > best[0]:
                best = (score, start, end, text)
    if best is None:
        return None
    _, start, end, text = best
    original_start = item.get("start_line")
    return {
        "evidence_id": item["evidence_id"],
        "kind": item.get("kind", "source_fact"),
        "path": item.get("path", "unknown"),
        "start_line": original_start + start if original_start is not None else None,
        "excerpt_end_line": original_start + end if original_start is not None else None,
        "end_line": item.get("end_line"),
        "sha256": item.get("sha256"),
        "text": text,
        "truncated": bool(item.get("truncated")) or start > 0 or end < len(lines) - 1,
        "selection_category": role,
    }


def _candidates(evidence: dict, workflow: str) -> list[tuple[dict, str]]:
    ranked = list(evidence["workflows"][workflow])
    known = {item["evidence_id"] for item in ranked}
    chunks = {item["evidence_id"]: item for item in evidence.get("chunks", [])}
    # Rails' shared controller contains identity and permission helpers relevant to dispatch.
    # Include those public helper facts even if lexical ranking omits them. Their execution
    # remains an inference, not an observed call.
    for item in chunks.values():
        if (
            item.get("path") == "app/controllers/application_controller.rb"
            and item.get("symbol") in {"find_current_user", "authorize"}
            and item["evidence_id"] not in known
        ):
            ranked.append(item)
            known.add(item["evidence_id"])
    seeds = {item["evidence_id"] for item in ranked[:8]}
    for edge in evidence.get("dependency_edges", []):
        target = chunks.get(edge.get("to"))
        if (
            edge.get("from") in seeds
            and target
            and target["evidence_id"] not in known
            and edge.get("ambiguous") is False
            and edge.get("kind") in {"possible_call", "possible_api_template"}
        ):
            ranked.append(target)
            known.add(target["evidence_id"])
    preferred, used = [], set()
    for role in PRIORITIES[workflow]:
        match = next((item for item in ranked if category(item, workflow) == role), None)
        if match:
            preferred.append((match, role))
            used.add(match["evidence_id"])
    preferred.extend(
        (item, category(item, workflow)) for item in ranked if item["evidence_id"] not in used
    )
    return preferred


def pack_sources(
    evidence: dict,
    workflows: list[str],
    *,
    byte_budget: int,
    max_documents: int = 6,
    primary_roles_first: bool = False,
    required_spans: tuple[tuple[str, int, int, str], ...] = (),
) -> list[dict]:
    """Diversify workflow/role coverage under an exact serialized source-array byte cap."""
    if byte_budget < 2:
        return []
    queues = [_candidates(evidence, workflow) for workflow in workflows]
    candidates, seen = [], set()
    if primary_roles_first and queues:
        # Reserve the primary workflow's distinct roles before interleaving support routes.
        primary, covered = queues[0], set()
        for item, role in primary:
            if role in PRIORITIES[workflows[0]] and role not in covered:
                candidates.append((item, role))
                covered.add(role)
                seen.add(item["evidence_id"])
        for queue in queues[1:]:
            match = next(((item, role) for item, role in queue if role == "entrypoint"), None)
            if match and match[0]["evidence_id"] not in seen:
                candidates.append(match)
                seen.add(match[0]["evidence_id"])
    for index in range(max((len(queue) for queue in queues), default=0)):
        for queue in queues:
            if index < len(queue) and queue[index][0]["evidence_id"] not in seen:
                candidates.append(queue[index])
                seen.add(queue[index][0]["evidence_id"])
    excerpts = []
    for path, start, end, role in required_spans:
        item = next(
            (
                chunk
                for chunk in evidence.get("chunks", [])
                if chunk.get("path") == path
                and chunk["start_line"] <= start <= end <= chunk["end_line"]
            ),
            None,
        )
        if item is None:
            continue
        lines = item["text"].splitlines(keepends=True)
        offset = start - item["start_line"]
        span = lines[offset : offset + end - start + 1]
        if len(span) != end - start + 1:
            continue
        excerpt = {
            "evidence_id": item["evidence_id"],
            "path": path,
            "sha256": item["sha256"],
            "start_line": start,
            "end_line": item["end_line"],
            "excerpt_end_line": end,
            "text": "".join(span),
            "truncated": True,
            "selection_category": role,
            "coverage_roles": [f"{workflows[0]}:{role}"],
        }
        if len(excerpts) < max_documents and source_bytes([*excerpts, excerpt]) <= byte_budget:
            excerpts.append(excerpt)
    anchored_ids = {item["evidence_id"] for item in excerpts}
    candidates = [
        (item, role) for item, role in candidates if item["evidence_id"] not in anchored_ids
    ]
    target_count = min(max_documents - len(excerpts), len(candidates))
    if target_count <= 0:
        return excerpts
    # Reserve each candidate's actual metadata first. Fill only complete source lines with
    # what remains. A small request can therefore omit a document rather than invent a fragment.
    empty = [
        {
            **item,
            "text": "",
            "truncated": True,
            "selection_category": role,
            "excerpt_end_line": item.get("end_line"),
        }
        for item, role in candidates[:target_count]
    ]
    allowance = max(80, min(700, (byte_budget - source_bytes([*excerpts, *empty])) // target_count))
    for item, role in candidates:
        excerpt = _line_window(item, allowance, role)
        if excerpt is None:
            continue
        if source_bytes([*excerpts, excerpt]) <= byte_budget:
            excerpt["coverage_roles"] = sorted(
                {
                    f"{workflow}:{candidate_role}"
                    for workflow, queue in zip(workflows, queues, strict=True)
                    for candidate, candidate_role in queue
                    if candidate["evidence_id"] == item["evidence_id"]
                }
            )
            excerpts.append(excerpt)
        if len(excerpts) == max_documents:
            break
    return excerpts
