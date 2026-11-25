"""Permission mappings must be literal source declarations with scoped receivers."""

import hashlib
import json

import pytest

from legacylift.modernization import access_control
from legacylift.modernization.access_control import extract_access_control, permission_evidence
from legacylift.modernization.repository import source_manifest
from legacylift.runtimes.redmine import REDMINE_SOURCE_COMMIT


def test_literal_declaration_keeps_exact_utf8_span_and_controller_actions():
    source = (
        "# 移行\nRedmine::AccessControl.map do |registry|\n"
        "  registry.project_module :issues do |permissions|\n"
        "    permissions.permission :edit_issues, {:issues => [:edit, :update],\n"
        "      :attachments => :upload}, :require => :member\n"
        "  end\nend\n"
    ).encode()
    report = extract_access_control(source)
    assert report["status"] == "parsed" and not report["unknowns"]
    (fact,) = report["bindings"]
    assert fact["permission"] == "edit_issues"
    assert fact["controller_actions"] == {"issues": ["edit", "update"], "attachments": ["upload"]}
    assert fact["start_line"] == 4 and fact["end_line"] == 5
    assert fact["text"].encode() in source
    assert hashlib.sha256(fact["text"].encode()).hexdigest() == fact["sha256"]
    assert fact["file_sha256"] == hashlib.sha256(source).hexdigest()
    assert fact["evidence_id"] == "ruby-permission:lib/redmine.rb:4:5"


@pytest.mark.parametrize(
    "body",
    [
        "other.permission :fake, {:issues => :update}",
        "unrelated do |map|\n map.permission :fake, {:issues => :update}\nend",
        "def helper\n map.permission :fake, {:issues => :update}\nend",
        "map = other\nmap.permission :fake, {:issues => :update}",
        "unrelated do\n map = other\nend\nmap.permission :fake, {:issues => :update}",
        "unrelated do |(map, extra)|\n map.permission :fake, {:issues => :update}\nend",
    ],
)
def test_unknown_shadowed_or_rebound_receiver_is_not_treated_as_access_control(body):
    source = f"Redmine::AccessControl.map do |map|\n{body}\nend\n".encode()
    report = extract_access_control(source)
    assert report["status"] == "parsed"
    assert not report["bindings"]


@pytest.mark.parametrize(
    "declaration",
    [
        "map.permission permission_name, {:issues => :update}",
        "map.permission :edit_issues, dynamic_routes",
        "map.permission :edit_issues, {:issues => [:edit, dynamic_action]}",
        "map.permission :edit_issues, {:issues => :update, :issues => dynamic_actions}",
        "map.permission :edit_issues, {:issues => :update, dynamic_controller => :show}",
    ],
)
def test_dynamic_values_are_reported_and_never_guessed(declaration):
    report = extract_access_control(
        f"Redmine::AccessControl.map do |map|\n{declaration}\nend\n".encode()
    )
    assert report["status"] == "parsed"
    assert not report["bindings"]
    assert report["unknowns"]


def test_syntax_error_fails_closed_without_executing_source():
    source = b"raise 'must never run'\nRedmine::AccessControl.map do |map|\n"
    report = extract_access_control(source)
    assert report["status"] == "parse_error"
    assert not report["bindings"]


@pytest.fixture
def public_source(tmp_path):
    root = tmp_path / "repositories" / REDMINE_SOURCE_COMMIT
    (root / "lib").mkdir(parents=True)
    source = root / "lib/redmine.rb"
    source.write_text(
        "Redmine::AccessControl.map do |map|\n"
        "map.permission :edit_issues, {:issues => [:edit, :update]}\nend\n",
        encoding="utf-8",
    )
    provenance = root.parent / f"{REDMINE_SOURCE_COMMIT}.json"
    provenance.write_text(
        json.dumps({**source_manifest(root), "commit": REDMINE_SOURCE_COMMIT}), encoding="utf-8"
    )
    return tmp_path, source, provenance


def test_missing_source_reports_unknown_without_fetch_or_write(tmp_path):
    report = permission_evidence(tmp_path, {"update"})
    assert report["status"] == "source_unavailable" and not report["bindings"]
    assert report["unknowns"] and not (tmp_path / "repositories").exists()


def test_loader_filters_actions_and_preserves_source_and_provenance(public_source):
    workspace, source, provenance = public_source
    before = source.read_bytes(), provenance.read_bytes()
    report = permission_evidence(workspace, {"update"})
    assert [f["permission"] for f in report["bindings"]] == ["edit_issues"]
    assert report["source_commit"] == REDMINE_SOURCE_COMMIT
    assert report["literal_route_declaration_count"] == 1
    assert not permission_evidence(workspace, {"show"})["bindings"]
    assert before == (source.read_bytes(), provenance.read_bytes())


def test_loader_rejects_modified_source(public_source):
    workspace, source, _ = public_source
    source.write_text("raise 'tampered source'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity manifest"):
        permission_evidence(workspace, {"update"})


def test_loader_rejects_change_between_tree_verification_and_read(public_source, monkeypatch):
    workspace, source, _ = public_source
    verify = access_control.verify_source_tree

    def raced(root, provenance):
        report = verify(root, provenance)
        source.write_text("raise 'changed after verification'\n", encoding="utf-8")
        return report

    monkeypatch.setattr(access_control, "verify_source_tree", raced)
    with pytest.raises(ValueError, match="changed after"):
        permission_evidence(workspace, {"update"})


@pytest.mark.parametrize(
    ("condition", "inference_count", "byte_limit"),
    [("hybrid", 0, 14_000), ("source_only", 2, 16_000)],
)
def test_prompt_projection_keeps_permissions_while_bounding_inferred_metadata(
    condition, inference_count, byte_limit
):
    from legacylift.modernization.generation import prompt_for

    facts = extract_access_control(
        b"Redmine::AccessControl.map do |map|\n"
        b"map.permission :edit_issues, {:issues => :update}\nend\n"
    )["bindings"]
    context = {
        "workflow": "update",
        "condition": condition,
        "source": [],
        "permission_bindings": facts,
        "rails_inferences": [{"text": "x" * 4000} for _ in range(5)],
        "workflow_bindings": [{"text": "y" * 10000}],
        "permission_extraction": {"status": "parsed"},
        "source_selection": {"serialized_source_byte_budget": 0},
    }
    before = json.dumps(context)
    prompt = prompt_for(context)
    payload = json.loads(prompt.split("EVIDENCE_JSON:\n", 1)[1])
    assert payload["permission_bindings"][0]["permission"] == "edit_issues"
    assert len(payload["rails_inferences"]) == inference_count
    assert "workflow_bindings" not in payload and "source_selection" not in payload
    assert len(prompt.encode("utf-8")) <= byte_limit
    assert json.dumps(context) == before
