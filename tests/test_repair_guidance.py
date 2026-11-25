"""Repair requests reuse exact permitted input/output evidence under a byte cap."""

import json
from pathlib import Path

import pytest

from legacylift.modernization.generation import (
    TARGET_DATABASE_CONTRACT,
    TARGET_REQUEST_BODY_CONTRACT,
    _repair_guidance_examples,
    _runtime_guidance,
    prompt_for,
)


def test_null_and_absent_keys_remain_distinguishable_in_repair_feedback():
    from legacylift.modernization.contracts import differences
    from legacylift.modernization.generation import _compact_repair_feedback

    missing = differences({"nullable": None}, {})[0]
    extra = differences({}, {"nullable": None})[0]
    assert missing["expected_present"] and not missing["actual_present"]
    assert extra["actual_present"] and not extra["expected_present"]
    compact = _compact_repair_feedback(
        {"mismatches": [{"scenario_id": "create.basic", "mismatches": [missing, extra]}]},
        diagnostic_bytes=0,
        scenario_limit=6,
        mismatch_limit=8,
        value_bytes=160,
    )
    assert compact["mismatches"][0]["mismatches"] == [missing, extra]


def test_repair_source_references_locate_single_quoted_response_keys():
    from legacylift.modernization.generation import _repair_source_references

    source = "# padding\n" * 40 + "response_issue = {'created_on': broken_time}\n"
    references = _repair_source_references(
        source,
        {"mismatches": [{"mismatches": [{"path": "steps[0].response.json.issue.created_on"}]}]},
    )
    assert "41: response_issue =" in references


@pytest.mark.parametrize("condition", ["source_only", "runtime_only", "hybrid"])
def test_request_body_contract_is_shared_by_initial_and_repair_prompts(condition):
    import inspect

    from fastapi import Request

    assert inspect.iscoroutinefunction(Request.body)
    assert inspect.iscoroutinefunction(Request.json)
    context = {"workflow": "update", "condition": condition, "source": [], "runtime": []}
    assert TARGET_REQUEST_BODY_CONTRACT in prompt_for(context)
    prompt = prompt_for(context, previous="app = None\n", feedback={})
    assert TARGET_REQUEST_BODY_CONTRACT in prompt
    assert len(prompt.encode("utf-8")) <= 16000


def test_runtime_deltas_keep_inserted_values_changed_nulls_and_row_identity():
    before = {"id": 1, "status_id": 1, "closed_on": "old", "subject": "unchanged"}
    case = {
        "scenario_id": "update.close",
        "steps": [
            {
                "request": {},
                "response": {"status": 204, "headers": {}, "json": None},
                "database_before": {"issues": [before]},
                "database_after": {
                    "issues": [
                        {**before, "status_id": 2, "closed_on": None, "description": None},
                        {"id": 2, "status_id": 1, "subject": "inserted", "closed_on": None},
                    ]
                },
            }
        ],
    }
    rows = _runtime_guidance(case)["steps"][0]["changed_rows"]["issues"]
    assert rows == [
        {"id": 1, "status_id": 2, "closed_on": None, "description": None},
        {"id": 2, "status_id": 1, "subject": "inserted", "closed_on": None},
    ]
    assert before == {"id": 1, "status_id": 1, "closed_on": "old", "subject": "unchanged"}


def example(identifier, *, status=201, body=None):
    return {
        "evidence_id": "runtime:" + identifier,
        "steps": [
            {
                "request": {
                    "method": "POST",
                    "path": "/issues.json",
                    "actor": "alice",
                    "json_body": body or {"issue": {"project_id": 1, "subject": "Synthetic"}},
                    "headers": {"X-Redmine-API-Key": "private-request-header-marker"},
                },
                "response": {
                    "status": status,
                    "body_empty": False,
                    "headers": {"cache-control": "no-cache", "set-cookie": "private-header-marker"},
                    "json": {"errors": ["Subject cannot be blank"]}
                    if status == 422
                    else {"issue": {"private": "not-forwarded"}},
                },
            }
        ],
    }


def feedback(*identifiers):
    return {
        "mismatches": [
            {
                "scenario_id": identifier,
                "split": "guidance",
                "passed": False,
                "mismatches": [
                    {"path": "steps[0].response.status", "expected": 201, "actual": 422}
                ],
            }
            for identifier in identifiers
        ]
    }


def test_repair_preserves_missing_request_fields_and_expected_response_without_private_headers(
    monkeypatch,
):
    context = {
        "condition": "hybrid",
        "runtime": [example("create.basic"), example("create.blank", status=422)],
    }
    monkeypatch.setattr(Path, "open", lambda *a, **k: pytest.fail("repair context read a file"))
    cases = _repair_guidance_examples(context, feedback("create.basic", "create.blank"))
    assert len(cases) == 2
    step = cases[0]["steps"][0]
    assert "status_id" not in step["request"]["json_body"]["issue"]
    assert step["expected_response"]["status"] == 201
    assert cases[1]["steps"][0]["expected_response"]["errors"] == ["Subject cannot be blank"]
    assert "private-" not in json.dumps(cases)
    assert "not-forwarded" not in json.dumps(cases)


def test_repair_excludes_held_out_unknown_passed_and_unsupplied_cases():
    context = {
        "condition": "runtime_only",
        "runtime": [
            example("create.unicode"),
            example("create.unknown_case"),
            example("create.basic"),
            example("create.blank", status=422),
        ],
    }
    failures = feedback(
        "create.unicode", "create.unknown_case", "create.basic", "create.long_subject"
    )
    failures["mismatches"][2]["passed"] = True
    assert _repair_guidance_examples(context, failures) == []


def test_source_only_never_gets_runtime_examples_even_if_accidentally_present():
    context = {"condition": "source_only", "runtime": [example("create.basic")]}
    assert _repair_guidance_examples(context, feedback("create.basic")) == []


def test_utf8_budget_omits_oversized_cases_without_truncating_selected_request():
    large = example("create.basic", body={"issue": {"subject": "漢" * 2000}})
    small = example("create.blank", status=422, body={"issue": {"subject": ""}})
    context = {"condition": "hybrid", "runtime": [large, small]}
    cases = _repair_guidance_examples(context, feedback("create.basic", "create.blank"))
    assert len(cases) == 1 and cases[0]["evidence_id"] == "runtime:create.blank"
    assert cases[0]["steps"][0]["request"]["json_body"] == small["steps"][0]["request"]["json_body"]
    assert len(json.dumps(cases, ensure_ascii=False, separators=(",", ":")).encode()) <= 1400


def test_status_mismatch_priority_retains_primary_example_and_source_in_actual_repair_prompt():
    context = {
        "workflow": "create",
        "condition": "runtime_only",
        "source": [],
        "runtime": [example("create.blank", status=422), example("create.basic")],
        "unknowns": [],
        "required_routes": [{"method": "POST", "path": "/issues.json"}],
    }
    failures = feedback("create.blank", "create.basic")
    failures["mismatches"][0]["mismatches"][0]["path"] = "steps[0].response.headers.cache-control"
    source = "from fastapi import FastAPI\napp = FastAPI()\n" + "# source retained\n" * 400
    prompt = prompt_for(context, previous=source, feedback=failures)
    serialized = prompt.split("REPAIR_CONTEXT_JSON:\n", 1)[1].split("\nSOURCE_LINE_REFERENCES", 1)[
        0
    ]
    # Context ends before the optional control-flow/source blocks.
    payload, _ = json.JSONDecoder().raw_decode(serialized)
    assert payload["guidance_examples"][0]["evidence_id"] == "runtime:create.basic"
    assert source in prompt and TARGET_DATABASE_CONTRACT in prompt
    assert len(prompt.encode("utf-8")) <= 16_000
