"""Checks that bounded source requests keep real source spans and explicit evidence gaps."""

import hashlib

from legacylift.modernization.source_packing import pack_sources, prompt_source, source_bytes


def fact(identity, symbol, text, path="app/controllers/issues_controller.rb", line=10):
    return {
        "evidence_id": identity,
        "path": path,
        "symbol": symbol,
        "text": text,
        "start_line": line,
        "end_line": line + len(text.splitlines()) - 1,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "kind": "source_fact",
    }


def test_packed_identity_window_is_exact_complete_source_lines_with_unicode_and_escaping():
    raw = (
        "def find_current_user\n"
        + "  irrelevant_setup_call\n" * 30
        + (
            '  token = params[:api_key] # Résumé \\"\n'
            "  user = User.find_by_api_key(token)\n"
            "  return user || User.anonymous\nend\n"
        )
    )
    item = fact(
        "ruby:identity", "find_current_user", raw, "app/controllers/application_controller.rb", 100
    )
    evidence = {"workflows": {"read": [item]}}
    excerpts = pack_sources(evidence, ["read"], byte_budget=700)
    assert len(excerpts) == 1
    excerpt = excerpts[0]
    assert excerpt["start_line"] > 100
    expected = "".join(
        raw.splitlines(keepends=True)[
            excerpt["start_line"] - 100 : excerpt["excerpt_end_line"] - 100 + 1
        ]
    )
    assert excerpt["text"] == expected
    assert "find_by_api_key" in expected
    assert excerpt["truncated"] is True
    assert source_bytes(excerpts) <= 700
    outbound = prompt_source(excerpt)
    assert outbound["lines"] == [excerpt["start_line"], excerpt["excerpt_end_line"]]
    assert outbound["sha256"] == item["sha256"]


def test_overlong_line_is_omitted_instead_of_fabricating_a_partial_source_line():
    item = fact("ruby:long-line", "show", "x" * 4000 + "\n")
    assert pack_sources({"workflows": {"read": [item]}}, ["read"], byte_budget=700) == []


def test_workflow_round_robin_preserves_each_entrypoint_and_deduplicates_shared_identity():
    items = [
        fact(f"ruby:{symbol}", symbol, f"def {symbol}\n return value\nend\n")
        for symbol in ("show", "create", "update")
    ]
    identity = fact(
        "ruby:identity",
        "find_current_user",
        "def find_current_user\n User.current\nend\n",
        "app/controllers/application_controller.rb",
    )
    evidence = {
        "chunks": [*items, identity],
        "workflows": {workflow: [*items, identity] for workflow in ("read", "create", "update")},
    }
    excerpts = pack_sources(evidence, ["read", "create", "update"], byte_budget=4000)
    assert {item["evidence_id"] for item in excerpts[:3]} == {item["evidence_id"] for item in items}
    assert [item["evidence_id"] for item in excerpts].count("ruby:identity") == 1
    assert source_bytes(excerpts) <= 4000
    assert pack_sources(evidence, ["read"], byte_budget=1) == []


def test_update_budget_retains_all_six_high_priority_source_roles():
    from legacylift.modernization.generation import UPDATE_HYBRID_SOURCE_BYTE_BUDGET

    facts = [
        fact(
            "ruby:app/controllers/issues_controller.rb:183:228",
            "update",
            "def update\n  save_issue\nend\n",
            "app/controllers/issues_controller.rb",
        ),
        fact(
            "ruby:app/controllers/application_controller.rb:107:153",
            "find_current_user",
            "def find_current_user\n  token = api_key\nend\n",
            "app/controllers/application_controller.rb",
        ),
        fact(
            "ruby:app/controllers/application_controller.rb:302:317",
            "authorize",
            "def authorize\n  allowed_to?(:edit_issues)\nend\n",
            "app/controllers/application_controller.rb",
        ),
        fact(
            "ruby:app/models/issue.rb:1049:1090",
            "statuses_allowed",
            "def statuses_allowed?\n  status = workflow\nend\n",
            "app/models/issue.rb",
        ),
        fact(
            "ruby:app/models/issue.rb:863:865",
            "journal",
            "def journal\n  journal.save\nend\n",
            "app/models/issue.rb",
        ),
        fact(
            "ruby:app/controllers/issues_controller.rb:519:545",
            "issue_from_params",
            "def issue_from_params\n  attrs = safe_attributes\nend\n",
            "app/controllers/issues_controller.rb",
        ),
    ]

    excerpts = pack_sources(
        {"workflows": {"update": facts}},
        ["update"],
        byte_budget=UPDATE_HYBRID_SOURCE_BYTE_BUDGET,
    )

    assert {item["selection_category"] for item in excerpts} == {
        "entrypoint",
        "identity",
        "authorization",
        "transition",
        "audit",
        "assignment",
    }
    assert source_bytes(excerpts) <= UPDATE_HYBRID_SOURCE_BYTE_BUDGET
