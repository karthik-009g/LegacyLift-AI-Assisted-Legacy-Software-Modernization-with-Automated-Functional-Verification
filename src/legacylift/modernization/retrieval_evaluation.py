"""Offline development diagnostic of public Ruby source retrieval, with no oracle input."""

from __future__ import annotations

import json
import math
from pathlib import Path

from legacylift.runtimes.redmine import REDMINE_SOURCE_COMMIT

from .contracts import canonical_hash
from .repository import verify_source_tree
from .ruby import WORKFLOW_QUERIES, analyze_ruby, rank_workflow, select_source_excerpts
from .source_packing import PACKING_VERSION, source_bytes


def retrieval_metrics(ranked_ids: list[str], grades: dict[str, int], k: int) -> dict:
    """Unjudged documents count as zero; recall covers only the declared relevance set."""
    if k < 1 or not grades or len(ranked_ids) != len(set(ranked_ids)):
        raise ValueError("metrics require positive k, judgments and unique ranked IDs")
    selected = ranked_ids[:k]
    relevant = set(grades)
    hits = relevant.intersection(selected)
    dcg = sum((2 ** grades.get(item, 0) - 1) / math.log2(i + 2) for i, item in enumerate(selected))
    ideal = sum(
        (2**grade - 1) / math.log2(i + 2)
        for i, grade in enumerate(sorted(grades.values(), reverse=True)[:k])
    )
    first = next((i + 1 for i, item in enumerate(selected) if item in relevant), None)
    return {
        "k": k,
        "relevant_found": len(hits),
        "relevant_total": len(relevant),
        "labeled_precision": round(len(hits) / k, 6),
        "labeled_recall": round(len(hits) / len(relevant), 6),
        "ndcg": round(dcg / ideal, 6),
        "reciprocal_rank": round(1 / first, 6) if first else 0,
        "missing_evidence_ids": sorted(relevant - hits),
    }


def evaluate_retrieval(evidence: dict, judgments: dict) -> dict:
    if judgments.get("split") != "source_guidance_development":
        raise ValueError("retrieval judgments must use the source/guidance development split")
    if judgments.get("source_commit") != REDMINE_SOURCE_COMMIT:
        raise ValueError("retrieval judgments do not match the pinned source commit")
    if set(judgments.get("workflows", {})) != set(WORKFLOW_QUERIES):
        raise ValueError("retrieval judgments must cover the three selected workflows")
    by_key = {}
    for chunk in evidence["chunks"]:
        by_key.setdefault((chunk["path"], chunk["symbol"]), []).append(chunk)
    grades_by_workflow = {}
    for workflow, labels in judgments["workflows"].items():
        grades = {}
        for label in labels:
            matches = by_key.get((label["path"], label["symbol"]), [])
            if len(matches) != 1:
                raise ValueError(
                    f"missing or ambiguous relevance label: {workflow}/{label['symbol']}"
                )
            identity = matches[0]["evidence_id"]
            if (
                identity in grades
                or type(label["grade"]) is not int
                or label["grade"] not in {1, 2, 3}
            ):
                raise ValueError("relevance labels need unique source symbols and grades 1, 2 or 3")
            grades[identity] = label["grade"]
        if not grades:
            raise ValueError("each workflow needs relevance labels")
        grades_by_workflow[workflow] = grades

    strategies = {}
    for strategy in ("bm25", "workflow", "dependency"):
        rankings = {
            workflow: rank_workflow(
                evidence["chunks"],
                workflow,
                strategy=strategy,
                edges=evidence["dependency_edges"],
            )
            for workflow in WORKFLOW_QUERIES
        }
        results = {}
        for workflow, ranked in rankings.items():
            grades = grades_by_workflow[workflow]
            contexts = {}
            for condition in ("source_only", "hybrid"):
                source_evidence = {**evidence, "workflows": rankings}
                excerpts = select_source_excerpts(source_evidence, workflow, condition)
                baseline = select_source_excerpts(
                    source_evidence, workflow, condition, strategy="prefix"
                )
                identities = [item["evidence_id"] for item in excerpts]
                contexts[condition] = {
                    "excerpt_count": len(excerpts),
                    "text_characters": sum(len(item["text"]) for item in excerpts),
                    "truncated_excerpt_count": sum(item["truncated"] for item in excerpts),
                    "serialized_source_bytes": source_bytes(excerpts),
                    "labeled_document_recall": round(
                        len(set(identities) & set(grades)) / len(grades), 6
                    ),
                    "evidence_ids": identities,
                    "missing_evidence_ids": sorted(set(grades) - set(identities)),
                    "prefix_baseline_document_recall": round(
                        len({item["evidence_id"] for item in baseline} & set(grades)) / len(grades),
                        6,
                    ),
                }
            results[workflow] = {
                "at_k": {
                    str(k): retrieval_metrics([item["evidence_id"] for item in ranked], grades, k)
                    for k in (8, 16, 32)
                },
                "generation_source_budget": contexts,
                "top_8": [
                    {key: item[key] for key in ("evidence_id", "path", "symbol", "retrieval_score")}
                    | {"grade": grades.get(item["evidence_id"], 0)}
                    for item in ranked[:8]
                ],
            }
        strategies[strategy] = results
    return {
        "status": "measured",
        "scope": "three-query development diagnostic; no independent retrieval test set",
        "source_commit": REDMINE_SOURCE_COMMIT,
        "judgments_version": judgments["version"],
        "judgments_sha256": canonical_hash(judgments),
        "index_sha256": canonical_hash(
            [
                {"evidence_id": item["evidence_id"], "sha256": item["sha256"]}
                for item in evidence["chunks"]
            ]
        ),
        "source_file_count": evidence["source_file_count"],
        "method_count": evidence["method_count"],
        "parse_error_files": evidence["parse_error_files"],
        "model_requests": 0,
        "held_out_read": False,
        "runtime_execution": False,
        "source_packing_version": PACKING_VERSION,
        "source_budget_scope": (
            "Standalone serialized source ceilings; actual generation first reserves complete "
            "instructions/runtime/schema metadata and may retain fewer excerpts."
        ),
        "strategies": strategies,
        "limitations": [
            "Judgments were authored after the existing anchors; this is development-set evidence.",
            "Unjudged source symbols are treated as irrelevant; labels are not exhaustive.",
            "Document recall does not prove the retained excerpt contains the required semantics.",
            "BM25 ablation and workflow ranking share the same parser, corpus and query strings.",
            "Static call edges are possible name matches; no runtime call coverage is measured.",
            "Retrieval scores do not establish generated-code compatibility or security.",
        ],
    }


def run_retrieval_evaluation(workspace: Path, judgments_path: Path, output: Path) -> dict:
    """Read public source/provenance only; never open study or model-run artifacts."""
    provenance = json.loads(
        (workspace / "repositories" / f"{REDMINE_SOURCE_COMMIT}.json").read_text(encoding="utf-8")
    )
    if provenance.get("commit") != REDMINE_SOURCE_COMMIT:
        raise ValueError("source provenance commit differs")
    source_root = workspace / "repositories" / REDMINE_SOURCE_COMMIT
    integrity = verify_source_tree(source_root, provenance)
    judgments = json.loads(judgments_path.read_text(encoding="utf-8"))
    evidence = analyze_ruby(source_root)
    report = evaluate_retrieval(evidence, judgments)
    report["source_tree_sha256"] = integrity["source_tree_sha256"]
    report["source_integrity_baseline"] = integrity.get("integrity_baseline", "recorded_manifest")
    report["retriever_sha256"] = canonical_hash(
        Path(__file__).with_name("ruby.py").read_text(encoding="utf-8")
    )
    report["source_packer_sha256"] = canonical_hash(
        Path(__file__).with_name("source_packing.py").read_text(encoding="utf-8")
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def audit_prompt_budgets(workspace: Path, output: Path, *, profile: str | None = None) -> dict:
    """Measure actual guidance-only requests without loading keys or sending them."""
    from .generation import build_context, prompt_byte_limit, prompt_for

    variants = []
    for workflow in ("read", "create", "update", "all"):
        for condition in ("source_only", "runtime_only", "hybrid"):
            context = (
                build_context(workspace, workflow, condition, profile=profile)
                if profile
                else build_context(workspace, workflow, condition)
            )
            prompt = prompt_for(context)
            outbound = json.loads(prompt.split("EVIDENCE_JSON:\n", 1)[1])
            variants.append(
                {
                    "workflow": workflow,
                    "condition": condition,
                    "prompt_bytes": len(prompt.encode("utf-8")),
                    "prompt_limit_bytes": prompt_byte_limit(context),
                    "prompt_sha256": canonical_hash(prompt),
                    "source_count": len(context["source"]),
                    "permission_binding_ids": [
                        item["evidence_id"] for item in outbound.get("permission_bindings", [])
                    ],
                    "rails_inferences_sent": len(outbound.get("rails_inferences", [])),
                    "rails_inferences_omitted": len(context.get("rails_inferences", []))
                    - len(outbound.get("rails_inferences", [])),
                    "context_metadata_omitted": sorted(set(context) - set(outbound)),
                    "serialized_source_bytes": source_bytes(context["source"]),
                    "source_spans": [
                        {
                            key: item[key]
                            for key in (
                                "evidence_id",
                                "start_line",
                                "excerpt_end_line",
                                "truncated",
                                "selection_category",
                            )
                        }
                        for item in context["source"]
                    ],
                    "source_selection": context.get("source_selection"),
                    "runtime_selection": context.get("runtime_selection"),
                }
            )
    report = {
        "status": "passed",
        "scope": "guidance-only request construction; no provider or candidate execution",
        "source_packing_version": PACKING_VERSION,
        "prompt_limit_bytes": max(item["prompt_limit_bytes"] for item in variants),
        "generation_profile": profile or "groq-conservative-default",
        "limit_scope": (
            "UTF-8 user prompt including instructions and context; provider wrappers are additional"
        ),
        "variant_count": len(variants),
        "model_requests": 0,
        "held_out_read": False,
        "variants": variants,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
