"""Ruby syntax evidence and explicitly labeled Rails convention inferences."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import tree_sitter_ruby
from rank_bm25 import BM25Okapi
from tree_sitter import Language, Parser

WORKFLOW_QUERIES = {
    "create": (
        "IssuesController create build_new_issue_from_params save_issue_with_child_records "
        "Issue safe_attributes validate permissions journal"
    ),
    "read": (
        "IssuesController show find_issue authorize find_current_user Issue visible? "
        "visible_condition issue API template"
    ),
    "update": (
        "IssuesController update update_issue_from_params save_issue_with_child_records "
        "Issue safe_attributes validate new_statuses_allowed_to status journal"
    ),
}
# Anchor scores make workflow entry points and their key model/serializer dependencies outrank
# generic BM25 matches (for example, TimelogController#find_optional_issue for a read query).
WORKFLOW_ANCHORS = {
    "read": {
        ("app/controllers/issues_controller.rb", "show"): 100,
        ("app/views/issues/show.api.rsb", "show.api.rsb"): 92,
        ("app/controllers/application_controller.rb", "find_issue"): 84,
        ("app/models/issue.rb", "visible?"): 80,
        ("app/models/issue.rb", "visible_condition"): 76,
        ("app/controllers/application_controller.rb", "authorize"): 70,
        ("app/controllers/application_controller.rb", "find_current_user"): 64,
        ("app/models/issue.rb", "load_visible_relations"): 38,
    },
    "create": {
        ("app/controllers/issues_controller.rb", "create"): 100,
        ("app/controllers/issues_controller.rb", "build_new_issue_from_params"): 96,
        ("app/controllers/issues_controller.rb", "save_issue_with_child_records"): 86,
        ("app/models/issue.rb", "safe_attributes="): 80,
        ("app/models/issue.rb", "validate_issue"): 76,
        ("app/models/issue.rb", "validate_permissions"): 68,
        ("app/controllers/application_controller.rb", "authorize"): 60,
        ("app/controllers/application_controller.rb", "find_current_user"): 56,
        ("app/models/issue.rb", "init_journal"): 42,
        ("app/models/issue.rb", "create_journal"): 38,
    },
    "update": {
        ("app/controllers/issues_controller.rb", "update"): 100,
        ("app/controllers/issues_controller.rb", "update_issue_from_params"): 96,
        ("app/controllers/issues_controller.rb", "save_issue_with_child_records"): 86,
        ("app/models/issue.rb", "safe_attributes="): 80,
        ("app/models/issue.rb", "new_statuses_allowed_to"): 76,
        ("app/models/issue.rb", "validate_issue"): 70,
        ("app/models/issue.rb", "validate_permissions"): 66,
        ("app/models/issue_status.rb", "new_statuses_allowed_to"): 60,
        ("app/models/issue.rb", "init_journal"): 50,
        ("app/models/issue.rb", "create_journal"): 46,
        ("app/controllers/application_controller.rb", "authorize"): 42,
    },
}
CONVENTIONS = {
    "before_action",
    "before_filter",
    "validates",
    "validate",
    "before_save",
    "after_save",
    "belongs_to",
    "has_many",
    "safe_attributes",
    "scope",
}


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", text).lower())


def rank_workflow(
    chunks: list[dict], workflow: str, *, strategy="workflow", ranker=None, edges=()
) -> list:
    """Rank source facts; the plain BM25 strategy is an explicit diagnostic ablation."""
    if workflow not in WORKFLOW_QUERIES or strategy not in {"bm25", "workflow", "dependency"}:
        raise ValueError("unsupported workflow or retrieval strategy")
    if not chunks:
        return []
    if ranker is None:
        ranker = BM25Okapi(
            [tokens(item["path"] + " " + item["symbol"] + " " + item["text"]) for item in chunks]
        )
    scores = ranker.get_scores(tokens(WORKFLOW_QUERIES[workflow]))
    # Propagate only along unambiguous, explicitly labeled static relationships. Two hops
    # bound cycles; max pooling avoids promoting a node just because it has many callers.
    support = {}
    if strategy == "dependency":
        frontier = {
            item["evidence_id"]
            for item in chunks
            if (item["path"], item["symbol"]) in WORKFLOW_ANCHORS[workflow]
        }
        valid_ids = {item["evidence_id"] for item in chunks}
        visited = set(frontier)
        for weight in (24, 12):
            next_frontier = set()
            for edge in edges:
                if (
                    edge["from"] in frontier
                    and edge["to"] in valid_ids
                    and not edge.get("ambiguous", True)
                    and edge.get("kind") in {"possible_call", "possible_api_template"}
                ):
                    support.setdefault(edge["to"], {"bonus": weight, "from": []})
                    support[edge["to"]]["from"].append(edge["from"])
                    if edge["to"] not in visited:
                        next_frontier.add(edge["to"])
            visited |= next_frontier
            frontier = next_frontier
    ranked = []
    for item, bm25_score in zip(chunks, scores, strict=True):
        anchor = WORKFLOW_ANCHORS[workflow].get((item["path"], item["symbol"]), 0)
        penalty = (
            -18
            if item["path"].startswith("app/controllers/")
            and item["path"]
            not in {
                "app/controllers/issues_controller.rb",
                "app/controllers/application_controller.rb",
            }
            else 0
        )
        dependency = support.get(item["evidence_id"], {})
        score = float(bm25_score) + (anchor + penalty if strategy != "bm25" else 0)
        score += dependency.get("bonus", 0)
        ranked.append(
            {
                **item,
                "retrieval_score": round(score, 4),
                "retrieval_reason": (
                    "static_dependency_plus_workflow_bm25"
                    if dependency
                    else "workflow_anchor_plus_bm25"
                    if strategy != "bm25" and anchor
                    else "bm25"
                ),
                **(
                    {"retrieval_support_ids": sorted(set(dependency["from"]))} if dependency else {}
                ),
                "_score": score,
            }
        )
    ranked.sort(key=lambda item: (-item["_score"], item["evidence_id"]))
    for item in ranked:
        del item["_score"]
    return ranked[:32]


def select_source_excerpts(
    evidence: dict,
    workflow: str,
    condition: str,
    *,
    strategy="diverse",
    byte_budget=None,
    supporting_workflows=(),
    primary_roles_first=False,
    max_documents: int | None = None,
    required_spans: tuple[tuple[str, int, int, str], ...] = (),
) -> list[dict]:
    """Apply the generation source budget, also used by the offline retrieval diagnostic."""
    if workflow not in {*WORKFLOW_QUERIES, "all"} or condition not in {
        "source_only",
        "runtime_only",
        "hybrid",
    }:
        raise ValueError("unsupported workflow or evidence condition")
    if condition == "runtime_only":
        return []
    selected = [workflow] if workflow != "all" else ["read", "create", "update"]
    if strategy == "diverse":
        from .source_packing import pack_sources

        selected.extend(item for item in supporting_workflows if item not in selected)
        return pack_sources(
            evidence,
            selected,
            byte_budget=byte_budget
            if byte_budget is not None
            else (4000 if condition == "hybrid" else 6500),
            max_documents=max_documents
            if max_documents is not None
            else 9
            if workflow == "all"
            else 8
            if primary_roles_first
            else 6,
            primary_roles_first=primary_roles_first,
            required_spans=required_spans,
        )
    if strategy != "prefix":
        raise ValueError("unsupported source packing strategy")
    budget = (450 if workflow == "all" else 1800) if condition == "hybrid" else 3800
    per_workflow_budget = budget // len(selected)
    seen, excerpts = set(), []
    for selected_workflow in selected:
        workflow_budget = per_workflow_budget
        for item in evidence["workflows"][selected_workflow]:
            if item["evidence_id"] in seen or workflow_budget <= 0:
                continue
            seen.add(item["evidence_id"])
            text = item["text"][: min(900, workflow_budget, budget)]
            excerpts.append(
                {
                    "evidence_id": item["evidence_id"],
                    "kind": item.get("kind", "source_fact"),
                    "path": item.get("path", "unknown"),
                    "start_line": item.get("start_line"),
                    "excerpt_end_line": (
                        item["start_line"] + text.count("\n")
                        if item.get("start_line") is not None
                        else None
                    ),
                    "end_line": item.get("end_line"),
                    "sha256": item.get("sha256"),
                    "text": text,
                    "truncated": len(text) < len(item["text"]),
                }
            )
            budget -= len(text)
            workflow_budget -= len(text)
    return excerpts


def analyze_ruby(source_root: Path) -> dict:
    parser = Parser(Language(tree_sitter_ruby.language()))
    chunks, inferences, errors = [], [], []
    # Framework glue is relevant evidence too; no test fixtures or vendored gems are indexed.
    paths = sorted(
        {
            *source_root.glob("app/**/*.rb"),
            *source_root.glob("lib/**/*.rb"),
            source_root / "config/routes.rb",
        }
    )
    template_paths = sorted(source_root.glob("app/views/**/*.api.rsb"))
    source_file_count = 0
    method_count = 0
    for path in paths:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 2_000_000:
            continue
        source_file_count += 1
        raw = path.read_bytes()
        tree = parser.parse(raw)
        relative = path.relative_to(source_root).as_posix()
        if tree.root_node.has_error:
            errors.append(relative)
        pending = [tree.root_node]
        while pending:
            node = pending.pop()
            pending.extend(reversed(node.named_children))
            if node.type in {"method", "singleton_method"}:
                method_count += 1
                name = node.child_by_field_name("name")
                text = raw[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
                identity = f"{relative}:{node.start_point.row + 1}:{node.end_point.row + 1}"
                children = [node]
                calls = set()
                while children:
                    descendant = children.pop()
                    children.extend(descendant.named_children)
                    if descendant.type == "call":
                        method = descendant.child_by_field_name("method")
                        if method:
                            calls.add(method.text.decode())
                chunks.append(
                    {
                        "evidence_id": "ruby:" + identity,
                        "kind": "source_fact",
                        "path": relative,
                        "start_line": node.start_point.row + 1,
                        "end_line": node.end_point.row + 1,
                        "symbol": name.text.decode() if name else "unknown",
                        "calls": sorted(calls),
                        "sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "text": text[:12_000],
                        "truncated": len(text) > 12_000,
                    }
                )
            elif node.type == "call":
                method = node.child_by_field_name("method")
                if method and method.text.decode() in CONVENTIONS:
                    text = raw[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
                    inferences.append(
                        {
                            "kind": "rails_convention_inference",
                            "path": relative,
                            "line": node.start_point.row + 1,
                            "convention": method.text.decode(),
                            "text": text[:1500],
                            "confidence": "syntax_observed_semantics_unresolved",
                        }
                    )
    for path in template_paths:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 1_000_000:
            continue
        source_file_count += 1
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        relative = path.relative_to(source_root).as_posix()
        chunks.append(
            {
                "evidence_id": "template:" + relative,
                "kind": "api_template_fact",
                "path": relative,
                "start_line": 1,
                "end_line": max(1, text.count("\n") + bool(text)),
                "symbol": path.name,
                "calls": [],
                "sha256": hashlib.sha256(raw).hexdigest(),
                "text": text[:12_000],
                "truncated": len(text) > 12_000,
            }
        )
    by_symbol = {}
    for item in chunks:
        by_symbol.setdefault(item["symbol"], []).append(item)
    edges = []
    templates_by_path = {
        item["path"]: item for item in chunks if item["kind"] == "api_template_fact"
    }
    for caller in chunks:
        for call in caller["calls"]:
            candidates = by_symbol.get(call, [])
            local = [item for item in candidates if item["path"] == caller["path"]]
            for callee in (local or candidates)[:5]:
                if callee["evidence_id"] != caller["evidence_id"]:
                    edges.append(
                        {
                            "from": caller["evidence_id"],
                            "to": callee["evidence_id"],
                            "kind": "possible_call",
                            "confidence": "static_name_match",
                            "ambiguous": len(local or candidates) > 1,
                        }
                    )
        # Rails API render references and the conventional same-action template are
        # inferred links. They do not establish that a response branch was executed.
        if caller["path"].startswith("app/controllers/"):
            controller = Path(caller["path"]).stem.removesuffix("_controller")
            actions = {caller["symbol"]}
            actions.update(
                re.findall(
                    r"render\s*(?:\(?\s*)?(?::action\s*=>|action:)\s*['\"]([a-z_]+)['\"]",
                    caller["text"],
                )
            )
            template_names = {f"app/views/{controller}/{action}.api.rsb" for action in actions}
            for name in sorted(template_names):
                template = templates_by_path.get(name)
                if template:
                    edges.append(
                        {
                            "from": caller["evidence_id"],
                            "to": template["evidence_id"],
                            "kind": "possible_api_template",
                            "confidence": "rails_render_convention",
                            "ambiguous": False,
                        }
                    )
    corpus = [tokens(item["path"] + " " + item["symbol"] + " " + item["text"]) for item in chunks]
    ranker = BM25Okapi(corpus) if corpus else None
    workflows = {
        workflow: rank_workflow(chunks, workflow, ranker=ranker) for workflow in WORKFLOW_QUERIES
    }
    return {
        "schema_version": "2.0",
        "language": "ruby",
        "parser": "tree-sitter-ruby",
        "source_file_count": source_file_count,
        "method_count": method_count,
        "chunks": chunks,
        "rails_inferences": inferences,
        "dependency_edges": edges,
        "runtime_bindings": [
            {
                "workflow": workflow,
                "controller": "app/controllers/issues_controller.rb",
                "action": {"read": "show", "create": "create", "update": "update"}[workflow],
                "kind": "study_contract_binding",
                "confidence": "selected_workflow_contract_not_route_observation",
                "contract_path": path,
            }
            for workflow, path in (
                ("read", "GET /issues/{id}.json"),
                ("create", "POST /issues.json"),
                ("update", "PUT /issues/{id}.json"),
            )
        ],
        "parse_error_files": errors,
        "workflows": workflows,
        "unknowns": [
            "Dynamic dispatch, plugins and runtime metaprogramming are not resolved.",
            "Static relationships are hypotheses until corroborated by execution.",
            "Workflow route paths are study-contract bindings, not extracted route observations.",
            "Only the selected REST workflow slice will be migrated.",
        ],
    }


def write_ruby_evidence(source_root: Path, output: Path) -> dict:
    result = analyze_ruby(source_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return {
        "path": str(output),
        "methods": result["method_count"],
        "parse_error_files": result["parse_error_files"],
    }
