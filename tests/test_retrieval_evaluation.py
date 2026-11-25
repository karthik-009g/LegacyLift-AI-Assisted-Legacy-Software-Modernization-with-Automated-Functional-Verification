"""Checks for independently calculated retrieval metrics and guidance isolation."""

import json
import math
from pathlib import Path

import pytest

from legacylift.modernization.repository import source_manifest
from legacylift.modernization.retrieval_evaluation import (
    evaluate_retrieval,
    retrieval_metrics,
    run_retrieval_evaluation,
)
from legacylift.modernization.ruby import analyze_ruby, rank_workflow, select_source_excerpts
from legacylift.runtimes.redmine import REDMINE_SOURCE_COMMIT


def test_graded_metrics_match_hand_calculation_and_count_missing_documents():
    report = retrieval_metrics(["unknown", "a", "b"], {"a": 3, "b": 1, "missing": 2}, 3)
    expected_dcg = 7 / math.log2(3) + 1 / math.log2(4)
    expected_ideal = 7 + 3 / math.log2(3) + 1 / math.log2(4)
    assert report["ndcg"] == pytest.approx(expected_dcg / expected_ideal, abs=1e-6)
    assert report["labeled_precision"] == pytest.approx(2 / 3, abs=1e-6)
    assert report["labeled_recall"] == pytest.approx(2 / 3, abs=1e-6)
    assert report["reciprocal_rank"] == 0.5
    assert report["missing_evidence_ids"] == ["missing"]
    with pytest.raises(ValueError, match="unique"):
        retrieval_metrics(["a", "a"], {"a": 3}, 2)


def source_fixture(root):
    path = root / "app/controllers/issues_controller.rb"
    path.parent.mkdir(parents=True)
    path.write_text(
        "class IssuesController\n"
        "  def show; Issue.visible; end\n"
        "  def create; Issue.new; end\n"
        "  def update; Issue.save; end\nend\n",
        encoding="utf-8",
    )
    return {
        "version": "test-1",
        "source_commit": REDMINE_SOURCE_COMMIT,
        "split": "source_guidance_development",
        "workflows": {
            workflow: [
                {"path": "app/controllers/issues_controller.rb", "symbol": symbol, "grade": 3}
            ]
            for workflow, symbol in (("read", "show"), ("create", "create"), ("update", "update"))
        },
    }


def test_missing_ambiguous_and_non_development_labels_fail_closed(tmp_path):
    labels = source_fixture(tmp_path)
    evidence = analyze_ruby(tmp_path)
    assert evaluate_retrieval(evidence, labels)["status"] == "measured"
    labels["split"] = "held_out"
    with pytest.raises(ValueError, match="development"):
        evaluate_retrieval(evidence, labels)
    labels["split"] = "source_guidance_development"
    labels["workflows"]["read"][0]["symbol"] = "missing"
    with pytest.raises(ValueError, match="missing or ambiguous"):
        evaluate_retrieval(evidence, labels)
    labels["workflows"]["read"][0]["symbol"] = "show"
    evidence["chunks"].append(evidence["chunks"][0])
    with pytest.raises(ValueError, match="ambiguous"):
        evaluate_retrieval(evidence, labels)


def test_diagnostic_never_reads_study_or_runs_and_preserves_cached_evidence(tmp_path, monkeypatch):
    workspace = tmp_path / "home"
    source = workspace / "repositories" / REDMINE_SOURCE_COMMIT
    labels = source_fixture(source)
    provenance = {"commit": REDMINE_SOURCE_COMMIT, **source_manifest(source)}
    (source.parent / f"{REDMINE_SOURCE_COMMIT}.json").write_text(json.dumps(provenance))
    labels_path = tmp_path / "labels.json"
    labels_path.write_text(json.dumps(labels))
    cached = workspace / "evidence/redmine.json"
    cached.parent.mkdir()
    cached.write_text("cached evidence must remain untouched")
    original_read = Path.read_text

    def guarded_read(path, *args, **kwargs):
        if "study" in path.parts or "runs" in path.parts or path.name == ".env":
            pytest.fail(f"retrieval diagnostic opened private study/model state: {path.name}")
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    output = tmp_path / "report.json"
    first = run_retrieval_evaluation(workspace, labels_path, output)
    assert run_retrieval_evaluation(workspace, labels_path, output) == first
    assert first["held_out_read"] is False
    assert first["model_requests"] == 0
    assert first["runtime_execution"] is False
    assert cached.read_text() == "cached evidence must remain untouched"
    assert first["strategies"]["workflow"]["read"]["at_k"]["8"]["labeled_recall"] == 1


def test_report_and_generation_share_source_budget_with_explicit_truncation():
    chunks = [
        {"evidence_id": str(i), "text": "x" * 1200, "start_line": 1, "end_line": 1}
        for i in range(10)
    ]
    evidence = {"workflows": {workflow: chunks for workflow in ("read", "create", "update")}}
    assert select_source_excerpts(evidence, "read", "runtime_only") == []
    hybrid = select_source_excerpts(evidence, "read", "hybrid", strategy="prefix")
    assert len(hybrid) == 2
    assert sum(len(item["text"]) for item in hybrid) == 1800
    assert all(item["truncated"] for item in hybrid)
    assert (
        sum(
            len(item["text"])
            for item in select_source_excerpts(evidence, "all", "hybrid", strategy="prefix")
        )
        <= 450
    )


def test_dependency_ranking_preserves_static_provenance_and_ignores_ambiguous_edges(tmp_path):
    source_fixture(tmp_path)
    controller = tmp_path / "app/controllers/issues_controller.rb"
    controller.write_text(
        "class IssuesController\n"
        " def create; render :action => 'show'; end\n"
        " def show; helper; end\n"
        " def helper; show; end\nend\n"
    )
    template = tmp_path / "app/views/issues/show.api.rsb"
    template.parent.mkdir(parents=True)
    template.write_text("api.issue @issue\n")
    evidence = analyze_ruby(tmp_path)
    create = next(item for item in evidence["chunks"] if item["symbol"] == "create")
    template_id = "template:app/views/issues/show.api.rsb"
    link = next(
        edge
        for edge in evidence["dependency_edges"]
        if edge["from"] == create["evidence_id"] and edge["to"] == template_id
    )
    assert link["confidence"] == "rails_render_convention"
    assert link["kind"] == "possible_api_template"
    ranked = rank_workflow(evidence["chunks"], "create", strategy="dependency", edges=[link])
    item = next(item for item in ranked if item["evidence_id"] == template_id)
    assert item["retrieval_support_ids"] == [create["evidence_id"]]
    assert item["retrieval_reason"] == "static_dependency_plus_workflow_bm25"
    ambiguous = rank_workflow(
        evidence["chunks"], "create", strategy="dependency", edges=[{**link, "ambiguous": True}]
    )
    item = next(item for item in ambiguous if item["evidence_id"] == template_id)
    assert "retrieval_support_ids" not in item
