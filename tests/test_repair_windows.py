"""Partial repair views must bind exact source and confine every resolved edit."""

import json

import pytest

from legacylift.modernization.contracts import canonical_hash
from legacylift.modernization.generation import (
    SourceEdit,
    SourceRangeEdit,
    apply_source_edits,
    apply_source_ranges,
    prepare_prompt,
)
from legacylift.modernization.repair_windows import select_source_windows, visible_source_ranges


def view(source, start, end):
    return {
        "source_sha256": canonical_hash(source),
        "windows": [
            {
                "start_line": start,
                "end_line": end,
                "text": "".join(source.splitlines(keepends=True)[start - 1 : end]),
            }
        ],
    }


def test_source_windows_are_exact_bounded_deterministic_and_include_error_at_eof():
    source = "# 日本語\n" + "# padded source content " * 4 + "\n"
    source += ("# many unchanged lines " * 4 + "\n") * 500
    source += "if True:\n"
    packet = select_source_windows(source, [len(source.splitlines()) + 1], byte_budget=1800)
    assert packet == select_source_windows(source, [len(source.splitlines()) + 1], byte_budget=1800)
    assert packet["omitted_lines"] > 0
    assert any("if True:\n" in window["text"] for window in packet["windows"])
    assert len(json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode()) <= 1800
    assert visible_source_ranges(source, packet)


def test_visible_multiline_unicode_edit_preserves_all_other_source():
    source = "# 移行\n" + "before = 1\n" + "value = 'one'\nextra = 1\n" + "after = 2\n"
    old, new = "value = 'one'\nextra = 1\n", "value = '日本語'\nextra = 2\n"
    updated = apply_source_edits(
        source, [SourceEdit(line=3, old=old, new=new)], source_view=view(source, 3, 4)
    )
    assert updated == source.replace(old, new)


def test_unique_fallback_cannot_modify_hidden_source_using_a_visible_line_number():
    source = "hidden = 1\n" + "# spacer\n" * 20 + "visible = 2\n"
    packet = view(source, 21, 22)
    with pytest.raises(ValueError, match="outside the supplied"):
        apply_source_edits(
            source, [SourceEdit(line=22, old="hidden = 1", new="hidden = 3")], source_view=packet
        )


def test_edit_cannot_cross_window_end_into_unseen_line():
    source = "first = 1\nsecond = 2\nthird = 3\n"
    with pytest.raises(ValueError, match="outside the supplied"):
        apply_source_edits(
            source,
            [SourceEdit(line=2, old="second = 2\nthird = 3", new="x = 4")],
            source_view=view(source, 2, 2),
        )


def test_source_hash_and_visible_text_are_validated_before_edits():
    source = "visible = 1\n# hidden\n"
    packet = view(source, 1, 1)
    with pytest.raises(ValueError, match="checksum"):
        visible_source_ranges(source + "# changed outside view\n", packet)
    packet["windows"][0]["text"] = "forged source\n"
    with pytest.raises(ValueError, match="text differs"):
        visible_source_ranges(source, packet)


@pytest.mark.parametrize("start,end", [(0, 1), (2, 1), (1, 3), (True, 1)])
def test_invalid_line_ranges_fail_closed(start, end):
    source = "x = 1\n"
    packet = {
        "source_sha256": canonical_hash(source),
        "windows": [{"start_line": start, "end_line": end}],
    }
    with pytest.raises(ValueError, match="line bounds"):
        visible_source_ranges(source, packet)


def test_oversized_source_uses_patch_windows_even_after_rejected_edit():
    source = "app = None\n" + ("# unchanged padding " * 4 + "\n") * 500 + "broken = (\n"
    feedback = {
        "review": {"findings": [{"rule": "invalid_repair_edit", "line": len(source.splitlines())}]}
    }
    prepared = prepare_prompt(
        {"workflow": "update", "condition": "source_only"}, previous=source, feedback=feedback
    )
    assert prepared["response_format"] == "edits"
    assert prepared["source_view"]["source_sha256"] == canonical_hash(source)
    assert prepared["source_view"]["omitted_lines"] > 0
    assert "PREVIOUS_SOURCE_WINDOWS_JSON" in prepared["prompt"]
    assert "complete replacement app.py" not in prepared["prompt"]
    assert len(prepared["prompt"].encode()) <= 16000


def test_small_source_keeps_existing_complete_source_prompt():
    source = "app = None\n"
    prepared = prepare_prompt({"condition": "hybrid"}, previous=source, feedback={})
    assert prepared["source_view"] is None
    assert "PREVIOUS_SOURCE:\n" + source in prepared["prompt"]


@pytest.mark.parametrize("workflow", ["read", "update"])
def test_collapsed_source_regenerates_from_original_evidence(workflow):
    source = r"from fastapi import FastAPI\n\napp = FastAPI()\n"
    context = {
        "workflow": workflow,
        "condition": "hybrid",
        "database_schema": {"issues": ["lock_version:INTEGER"]},
        "runtime": [{"evidence_id": "runtime:update.advance", "steps": []}],
    }
    prepared = prepare_prompt(
        context,
        previous=source,
        feedback={"review": {"findings": [{"rule": "invalid_python", "line": 1}]}},
    )
    assert prepared["response_format"] == "source_lines"
    assert prepared["source_view"] is None
    assert "Regenerate from evidence below" in prepared["prompt"]
    assert "update.advance" in prepared["prompt"]
    assert "lock_version" in prepared["prompt"]
    assert source not in prepared["prompt"]
    assert len(prepared["prompt"].encode()) <= 14000


@pytest.mark.parametrize(
    "source",
    [
        "app.py:1: from fastapi import FastAPI\napp.py:2: app = FastAPI()\n",
        "app.py line 1: from fastapi import FastAPI\napp.py line 2: app = FastAPI()\n",
        "```python\nfrom fastapi import FastAPI\n```\n",
        "def invalid(:\n    pass\n",
    ],
)
def test_invalid_source_regenerates_without_editing_the_listing(source):
    context = {"workflow": "read", "condition": "hybrid", "runtime": [], "database_schema": {}}
    prepared = prepare_prompt(
        context,
        previous=source,
        feedback={"review": {"findings": [{"rule": "invalid_python", "line": 1}]}},
    )
    assert prepared["response_format"] == "source_lines"
    assert prepared["source_view"] is None
    assert "omit file/line labels" in prepared["prompt"]
    assert source not in prepared["prompt"]


def test_read_body_syntax_repair_includes_parser_line_and_preserves_scaffold():
    from legacylift.modernization.generation import READ_IMPLEMENTATION_PROTOCOL
    from legacylift.modernization.scaffold import (
        READ_SCAFFOLD,
        READ_SCAFFOLD_VERSION,
        create_scaffold_binding,
    )

    context = {
        "workflow": "read",
        "condition": "hybrid",
        "runtime": [],
        "database_schema": {},
        "source_assembly": create_scaffold_binding(READ_SCAFFOLD_VERSION),
        "implementation_protocol": READ_IMPLEMENTATION_PROTOCOL,
        "read_syntax_repair": "parser-window-v1",
    }
    bad_line = "    if include not not in ('journals', None):"
    source = (
        READ_SCAFFOLD + f"def read_issue(api_key, issue_id, include):\n{bad_line}\n        pass\n"
    )
    target = READ_SCAFFOLD.count("\n") + 2
    feedback = {"review": {"findings": [{"rule": "invalid_python", "line": target}]}}
    repair = prepare_prompt(context, previous=source, feedback=feedback)
    assert repair["response_format"] == "line_edits"
    assert bad_line in repair["prompt"]
    assert all(
        window["start_line"] > READ_SCAFFOLD.count("\n")
        for window in repair["source_view"]["windows"]
    )
    listing = source.replace(bad_line, "    app.py:123: if include:")
    regenerated = prepare_prompt(context, previous=listing, feedback=feedback)
    assert regenerated["response_format"] == "read_handlers"
    assert regenerated["source_view"] is None


def test_update_repair_exposes_numbered_lines_and_applies_range_without_old_text():
    source = "def process(db):\n    row = db.execute(query).fetchone()\n    return row['id']\n"
    prepared = prepare_prompt(
        {"workflow": "update", "condition": "hybrid"},
        previous=source,
        feedback={"diagnostics": 'File "/candidate/app.py", line 3, in process'},
    )
    assert prepared["response_format"] == "line_edits"
    assert '[2,"    row = db.execute(query).fetchone()"]' in prepared["prompt"]
    result = apply_source_ranges(
        source,
        [
            SourceRangeEdit(
                start_line=2,
                end_line=2,
                new_lines=["    row = db.execute(query).mappings().first()"],
            ),
        ],
        source_view=prepared["source_view"],
    )
    assert result == source.replace("fetchone()", "mappings().first()")


def test_create_hybrid_keeps_defaults_in_generation_and_numbered_repair():
    from legacylift.modernization.generation import CREATE_EFFECTS_CONTRACT, prompt_byte_limit

    context = {"workflow": "create", "condition": "hybrid"}
    initial = prepare_prompt(context)
    repair = prepare_prompt(context, previous="app = None\n", feedback={})
    assert initial["response_format"] == "source_lines"
    assert repair["response_format"] == "line_edits"
    assert "POST /issues.json only" in initial["prompt"]
    assert "add_issues" in initial["prompt"]
    for item in (initial, repair):
        assert CREATE_EFFECTS_CONTRACT in item["prompt"]
        assert len(item["prompt"].encode()) <= prompt_byte_limit(context) == 14_000


def test_create_repair_keeps_separated_permission_insert_and_response_windows():
    spacer = "# unchanged code\n" * 300
    source = (
        spacer
        + "    if 'add_issues' in perms.split(','):\n"
        + spacer
        + "    db.execute(text('INSERT INTO issues (subject) VALUES (:subject)'))\n"
        + spacer
        + "    issue_resp = {'id': new_id}\n"
        + spacer
    )
    prepared = prepare_prompt({"workflow": "create", "condition": "hybrid"}, previous=source)
    windows = "".join(window["text"] for window in prepared["source_view"]["windows"])
    assert "perms.split" in windows and "INSERT INTO issues" in windows
    assert "issue_resp =" in windows
    assert prepared["source_view"]["omitted_lines"] > 0


def test_outsider_create_repair_exposes_project_lookup_in_generated_handler():
    from legacylift.modernization.generation import CREATE_REPAIR_POLICY

    lines = ["def create_issue():"] + ["    value = 1"] * 180
    lines[91] = "    project = read_one('SELECT id FROM projects WHERE id=:id', params)"
    lines[110] = "    permissions = project_permissions(user_id, project_id)"
    lines[145] = "    write(conn, 'INSERT INTO issues (...)', params)"
    source = "\n".join(lines) + "\n"
    context = {
        "workflow": "create",
        "condition": "hybrid",
        "create_repair_policy": CREATE_REPAIR_POLICY,
    }
    feedback = {
        "mismatches": [
            {"scenario_id": "create.outsider", "mismatches": [{"path": "steps[0].response.status"}]}
        ]
    }
    windows = prepare_prompt(context, previous=source, feedback=feedback)["source_view"]["windows"]
    assert any(w["start_line"] <= 92 <= w["end_line"] for w in windows)
    assert any(w["start_line"] <= 111 <= w["end_line"] for w in windows)


def test_anonymous_create_repair_exposes_401_response():
    from legacylift.modernization.generation import CREATE_REPAIR_POLICY

    lines = ["def create_issue():"] + ["    value = 1"] * 180
    lines[79] = "    return Response(status_code=401, headers=headers)"
    lines[145] = "    write(conn, 'INSERT INTO issues (...)', params)"
    source = "\n".join(lines) + "\n"
    feedback = {
        "mismatches": [
            {
                "scenario_id": "create.anonymous",
                "mismatches": [{"path": "steps[0].response.headers.content-type"}],
            }
        ]
    }
    context = {
        "workflow": "create",
        "condition": "hybrid",
        "create_repair_policy": CREATE_REPAIR_POLICY,
    }
    view = prepare_prompt(context, previous=source, feedback=feedback)["source_view"]
    assert any(w["start_line"] <= 80 <= w["end_line"] for w in view["windows"])


def test_read_bodies_wire_and_parser_exclude_module_helpers():
    from pydantic import ValidationError

    from legacylift.modernization.generation import _parse_migration, _response_schema

    schema = _response_schema("read_bodies")
    assert "helper_lines" not in schema["properties"]
    response = {
        "summary": "Synthetic handler assembly",
        "evidence_ids": [],
        "unknowns": [],
        "read_body": ["return Response(status_code=404)"],
        "create_body": ["return Response(status_code=422)"],
        "update_body": ["return Response(status_code=204)"],
    }
    draft = _parse_migration(json.dumps(response), response_format="read_bodies")
    assert "def read_issue(api_key, issue_id, include):" in draft.source
    assert "    return Response(status_code=404)" in draft.source
    with pytest.raises(ValidationError):
        _parse_migration(
            json.dumps({**response, "helper_lines": ["def read_one(): pass"]}),
            response_format="read_bodies",
        )
    legacy = _parse_migration(
        json.dumps({**response, "helper_lines": ["def extra(): pass"]}),
        response_format="read_handlers",
    )
    assert "def extra(): pass" in legacy.source


def test_composed_read_preserves_reviewed_support_and_requests_two_model_bodies():
    from importlib.resources import files

    from pydantic import ValidationError

    from legacylift.modernization.generation import _parse_migration, _response_schema
    from legacylift.modernization.scaffold import (
        READ_COMPOSED_SCAFFOLD_VERSION,
        REVIEWED_UPDATE_BINDING,
        candidate_scaffold,
        create_interface_findings,
        create_scaffold_binding,
    )

    binding = create_scaffold_binding(READ_COMPOSED_SCAFFOLD_VERSION)
    context = {"workflow": "read", "condition": "hybrid", "source_assembly": binding}
    scaffold = candidate_scaffold(context)
    support = (
        files("legacylift.runtimes")
        .joinpath("assets/reviewed_update.py.txt")
        .read_text(encoding="utf-8")
    )
    assert canonical_hash(support) == REVIEWED_UPDATE_BINDING["source_sha256"]
    assert binding["supporting_implementations"] == [REVIEWED_UPDATE_BINDING]
    assert "return await _reviewed_update_handler(issue_id, request)" in scaffold
    schema = _response_schema("read_with_update")
    assert "update_body" not in schema["properties"]
    response = {
        "summary": "Synthetic read composition",
        "evidence_ids": [],
        "unknowns": [],
        "read_body": ["return Response(status_code=404)"],
        "create_body": ["return Response(status_code=422)"],
    }
    draft = _parse_migration(json.dumps(response), response_format="read_with_update")
    assert "def update_issue" not in draft.source
    assert create_interface_findings(scaffold, draft.source) == []
    with pytest.raises(ValidationError):
        _parse_migration(
            json.dumps({**response, "update_body": ["return None"]}),
            response_format="read_with_update",
        )
    binding["supporting_implementations"][0]["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="generation context"):
        candidate_scaffold(context)


def test_read_syntax_repair_shows_repeated_fstring_quote_errors():
    from legacylift.modernization.generation import _prepare_windowed_repair

    lines = ["def read_issue(api_key, issue_id, include):"] + ["    value = 1"] * 180
    bad = r'    name = f"{author[\"firstname\"]}"'
    lines[39] = lines[149] = bad
    source = "\n".join(lines) + "\n"
    context = {
        "workflow": "read",
        "condition": "hybrid",
        "read_syntax_windows": "related-fstrings-v1",
    }
    feedback = {
        "review": {
            "findings": [
                {
                    "rule": "invalid_python",
                    "line": 40,
                    "message": "unexpected character after line continuation character",
                }
            ]
        }
    }
    prepared = _prepare_windowed_repair(context, source, feedback, numbered_ranges=True)
    windows = prepared["source_view"]["windows"]
    assert all(any(w["start_line"] <= n <= w["end_line"] for w in windows) for n in (40, 150))
    assert bad in "".join(w["text"] for w in windows)


def test_matching_handler_wrapper_recovery_preserves_function_ast():
    import ast

    from legacylift.modernization.generation import normalize_read_body

    source = (
        "def create_issue(api_key, payload, base_url):\n    data = payload or {}\n    return data\n"
    )
    body, metadata = normalize_read_body("create_issue", source)
    assert metadata["raw_source_sha256"] == canonical_hash(source)
    assert metadata["normalized_source_sha256"] == canonical_hash(body)
    rebuilt = "def create_issue(api_key, payload, base_url):\n" + "\n".join(
        "    " + line for line in body.splitlines()
    )
    assert ast.dump(ast.parse(source), include_attributes=False) == ast.dump(
        ast.parse(rebuilt), include_attributes=False
    )
    different = source.replace("payload,", "document,")
    assert normalize_read_body("create_issue", different) == (different, None)
    outside = source + "print('outside')\n"
    assert normalize_read_body("create_issue", outside) == (outside, None)
    literal = 'def create_issue(api_key, payload, base_url):\n    return """first\nsecond"""\n'
    assert normalize_read_body("create_issue", literal) == (literal, None)


def test_read_response_imports_are_limited_to_leading_identical_sdk_classes():
    from legacylift.modernization.scaffold import READ_COMPOSED_SCAFFOLD, create_interface_findings

    read = "def read_issue(api_key, issue_id, include):\n    return None\n"
    create = (
        "def create_issue(api_key, payload, base_url):\n"
        "    from fastapi.responses import JSONResponse, Response\n"
        "    return Response(status_code=422)\n"
    )
    assert create_interface_findings(READ_COMPOSED_SCAFFOLD, read + create) == []
    for imported in ("FastAPI", "JSONResponse as DifferentResponse"):
        findings = create_interface_findings(
            READ_COMPOSED_SCAFFOLD, read + create.replace("JSONResponse, Response", imported)
        )
        assert "read_scaffold_override" in {item["rule"] for item in findings}
    conditional = create.replace(
        "    from fastapi.responses", "    if payload:\n        from fastapi.responses"
    )
    assert any(
        item["rule"] == "read_scaffold_override"
        for item in create_interface_findings(READ_COMPOSED_SCAFFOLD, read + conditional)
    )


def test_staged_post_evidence_shows_the_controller_payload_argument():
    from legacylift.modernization.generation import read_stage_prompt
    from legacylift.modernization.scaffold import (
        READ_COMPOSED_SCAFFOLD_VERSION,
        create_scaffold_binding,
    )

    context = {
        "workflow": "read",
        "condition": "hybrid",
        "source_assembly": create_scaffold_binding(READ_COMPOSED_SCAFFOLD_VERSION),
        "runtime": [
            {
                "evidence_id": "runtime:read.after_create",
                "steps": [
                    {
                        "request": {
                            "method": "POST",
                            "json_body": {"issue": {"subject": "Example"}},
                        },
                        "response": {"status": 201, "headers": {}, "json": {"issue": {}}},
                    }
                ],
            }
        ],
        "database_schema": {},
    }
    original = json.dumps(context, sort_keys=True)
    packet = json.loads(read_stage_prompt(context, "create_issue").split("EVIDENCE_JSON:\n", 1)[1])
    assert packet["handler_arguments"]["examples"][0]["payload_argument"] == {"subject": "Example"}
    assert json.dumps(context, sort_keys=True) == original


@pytest.mark.parametrize("handler,method", [("read_issue", "GET"), ("create_issue", "POST")])
def test_staged_v2_limits_task_and_guidance_to_one_endpoint(handler, method):
    from legacylift.modernization.generation import read_stage_prompt
    from legacylift.modernization.scaffold import (
        READ_COMPOSED_SCAFFOLD_VERSION,
        create_scaffold_binding,
    )

    steps = [
        {
            "request": {"method": verb, "path": "/issues.json", "json_body": {"issue": {}}},
            "response": {"status": 200, "headers": {}, "json": {}},
        }
        for verb in ("GET", "POST", "PUT")
    ]
    context = {
        "workflow": "read",
        "condition": "hybrid",
        "read_generation_strategy": "staged-bodies-v2",
        "source_assembly": create_scaffold_binding(READ_COMPOSED_SCAFFOLD_VERSION),
        "required_routes": [
            {"method": verb, "path": "/issues.json"} for verb in ("GET", "POST", "PUT")
        ],
        "runtime": [{"evidence_id": "runtime:read.after_create", "steps": steps}],
        "database_schema": {},
    }
    original = canonical_hash(context)
    prompt = read_stage_prompt(context, handler)
    instructions, serialized = prompt.split("EVIDENCE_JSON:\n", 1)
    packet = json.loads(serialized)
    assert packet["generation_target"] == handler
    assert {route["method"] for route in packet["required_routes"]} == {method}
    assert [step["request"]["method"] for step in packet["runtime"][0]["steps"]] == [method]
    assert "Define synchronous" not in instructions
    assert "no outer function declaration" in instructions
    assert canonical_hash(context) == original
    assert len(prompt.encode()) <= 14_000


def test_read_regeneration_budget_failure_falls_back_to_bound_windows(monkeypatch):
    from legacylift.modernization import generation

    source = "def read_issue(api_key, issue_id, include):\n    return None\n"
    context = {
        "workflow": "read",
        "condition": "hybrid",
        "implementation_protocol": generation.READ_IMPLEMENTATION_PROTOCOL,
        "read_body_interface": "controller-helpers-only-v1",
    }
    feedback = {"review": {"findings": [{"code": "invalid_repair_edit"}]}}
    original = generation._prompt_for_source

    def reject_regeneration(*args, **kwargs):
        if kwargs.get("regenerate_reason"):
            raise generation.PromptBudgetExceeded("regeneration prefix exceeds budget")
        return original(*args, **kwargs)

    monkeypatch.setattr(generation, "_prompt_for_source", reject_regeneration)
    prepared = generation.prepare_prompt(context, previous=source, feedback=feedback)
    assert prepared["response_format"] == "line_edits"
    assert prepared["source_view"]["source_sha256"] == canonical_hash(source)


def test_read_repair_keeps_whole_handler_and_reversible_schema():
    from legacylift.modernization.generation import _prepare_windowed_repair
    from legacylift.modernization.scaffold import (
        READ_SCAFFOLD,
        READ_SCAFFOLD_VERSION,
        create_scaffold_binding,
    )

    fragment = (
        "def read_issue(api_key, issue_id, include):\n"
        "    priority = None\n"
        "    return priority['id']\n"
        "\ndef create_issue(api_key, payload, base_url):\n    return None\n"
        "\ndef update_issue(api_key, issue_id, payload):\n    return None\n"
    )
    source = READ_SCAFFOLD + fragment
    first = READ_SCAFFOLD.count("\n") + 1
    schema = {"enumerations": ["id:INTEGER", "type:VARCHAR"]}
    context = {
        "workflow": "read",
        "condition": "hybrid",
        "source_assembly": create_scaffold_binding(READ_SCAFFOLD_VERSION),
        "read_repair_layout": "typed-schema-v1",
        "database_schema": schema,
    }
    feedback = {"diagnostics": f'File "/candidate/app.py", line {first + 2}\nTypeError: NoneType'}
    prepared = _prepare_windowed_repair(context, source, feedback, numbered_ranges=True)
    view = prepared["source_view"]
    assert view["handler"] == "read_issue"
    assert [(w["start_line"], w["end_line"]) for w in view["windows"]] == [(first, first + 2)]
    payload, _ = json.JSONDecoder().raw_decode(
        prepared["prompt"].split("REPAIR_CONTEXT_JSON:\n")[1]
    )
    restored = {
        table: [
            name + ":" + payload["db_type_codes"][code]
            for name, code in (column.split(":", 1) for column in columns.split())
        ]
        for table, columns in payload["database_schema"].items()
    }
    assert restored == schema
    with pytest.raises(ValueError, match="outside"):
        apply_source_ranges(
            source,
            [SourceRangeEdit(start_line=first + 5, end_line=first + 5, new_lines=["    return 1"])],
            source_view=view,
        )


def test_focused_create_repair_keeps_priority_query_and_caps_visible_spans():
    from legacylift.modernization.generation import CREATE_REPAIR_WINDOW_LINES

    lines = ["def create_issue():"] + ["    x = 1"] * 150
    lines[39] = '    priority = "IssuePriority"'
    lines[59] = '    insert = "INSERT INTO issues"'
    lines[79] = '    issue_resp = {"priority": priority}'
    source = "\n".join(lines) + "\n"
    context = {
        "workflow": "create",
        "condition": "hybrid",
        "create_repair_policy": "focused-windows-v1",
    }
    feedback = {
        "mismatches": [
            {
                "scenario_id": "create.basic",
                "mismatches": [{"path": "steps[0].database_after.issues[1].priority_id"}],
            }
        ]
    }
    prepared = prepare_prompt(context, previous=source, feedback=feedback)
    windows = prepared["source_view"]["windows"]
    assert all(w["end_line"] - w["start_line"] + 1 <= CREATE_REPAIR_WINDOW_LINES for w in windows)
    assert all(any(w["start_line"] <= n <= w["end_line"] for w in windows) for n in (40, 60, 80))
    with pytest.raises(ValueError, match="outside"):
        apply_source_ranges(
            source,
            [SourceRangeEdit(start_line=40, end_line=80, new_lines=["    return None"])],
            source_view=prepared["source_view"],
        )


@pytest.mark.parametrize(
    "version", ["fastapi-create-v1", "fastapi-create-v2", "fastapi-create-v3", "fastapi-create-v4"]
)
def test_scaffolded_repairs_exclude_controller_lines(version):
    from legacylift.modernization.scaffold import CREATE_SCAFFOLDS, create_scaffold_binding

    scaffold = CREATE_SCAFFOLDS[version]
    context = {
        "workflow": "create",
        "condition": "hybrid",
        "source_assembly": create_scaffold_binding(version),
    }
    source = scaffold + "value = 1\n"
    line = scaffold.count("\n") + 1
    prepared = prepare_prompt(context, previous=source)
    view = prepared["source_view"]
    assert min(window["start_line"] for window in view["windows"]) == line
    with pytest.raises(ValueError, match="outside the supplied"):
        apply_source_ranges(
            source, [SourceRangeEdit(start_line=1, end_line=1, new_lines=[])], source_view=view
        )
    updated = apply_source_ranges(
        source,
        [SourceRangeEdit(start_line=line, end_line=line, new_lines=["value = 2"])],
        source_view=view,
    )
    assert updated == scaffold + "value = 2\n"


def test_read_repair_covers_both_failing_handlers_when_complete_bodies_do_not_fit():
    import ast

    from legacylift.modernization.scaffold import (
        READ_COMPOSED_SCAFFOLD,
        READ_COMPOSED_SCAFFOLD_VERSION,
        create_scaffold_binding,
    )

    context = {
        "workflow": "read",
        "condition": "hybrid",
        "read_repair_layout": "typed-schema-v1",
        "read_response_contract": "explicit-response-contract-v1",
        "source_assembly": create_scaffold_binding(READ_COMPOSED_SCAFFOLD_VERSION),
        "runtime": [
            {
                "evidence_id": "runtime:example",
                "steps": [{"request": {"method": "POST"}}, {"request": {"method": "GET"}}],
            }
        ],
    }
    fragment = ""
    for signature in (
        "read_issue(api_key, issue_id, include)",
        "create_issue(api_key, payload, base_url)",
    ):
        fragment += f"def {signature}:\n" + ("    # unchanged padding " * 5 + "\n") * 150
        fragment += '    return JSONResponse({"issue": {"subject": "example"}})\n'
    source = READ_COMPOSED_SCAFFOLD + fragment
    feedback = {
        "status": "compatibility_failed",
        "mismatches": [
            {
                "scenario_id": "example",
                "mismatches": [
                    {
                        "path": "steps[0].response.json.issue.subject",
                        "expected": "new",
                        "actual": "example",
                    },
                    {
                        "path": "steps[1].response.json.issue.subject",
                        "expected": "new",
                        "actual": "example",
                    },
                ],
            }
        ],
    }
    prepared = prepare_prompt(context, previous=source, feedback=feedback)
    view_packet = prepared["source_view"]
    assert view_packet["handlers"] == ["read_issue", "create_issue"]
    assert len(prepared["prompt"].encode()) <= 14_000
    ranges = visible_source_ranges(source, view_packet)
    assert len(ranges) == 2
    nodes = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef) and node.name in view_packet["handlers"]
    ]
    for node, window in zip(nodes, view_packet["windows"], strict=True):
        assert node.lineno <= window["start_line"] <= window["end_line"] <= node.end_lineno


def test_v4_repairs_keep_typed_helpers_without_standalone_app_instructions():
    from legacylift.modernization.scaffold import (
        CREATE_SCAFFOLD,
        CREATE_SCAFFOLD_VERSION,
        create_scaffold_binding,
        scaffold_api,
    )

    context = {
        "workflow": "create",
        "condition": "hybrid",
        "source_assembly": create_scaffold_binding(),
    }
    fragment = (
        "def create_issue(api_key, payload, base_url):\n    return Response(status_code=401)\n"
    )
    prepared = prepare_prompt(context, previous=CREATE_SCAFFOLD + fragment)
    assert prepared["response_format"] == "line_edits"
    assert scaffold_api(CREATE_SCAFFOLD_VERSION) in prepared["prompt"]
    assert "frozenset[str]" in prepared["prompt"]
    assert "clock_now().strftime" in prepared["prompt"]
    assert "actually read the mounted file" not in prepared["prompt"]
    assert "active SQLAlchemy Session" not in prepared["prompt"]
    assert "no guessed IDs" in prepared["prompt"]


def test_controller_permission_helper_reads_exact_names_only_for_project_membership(monkeypatch):
    from legacylift.modernization.scaffold import CREATE_SCAFFOLD

    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    namespace = {}
    # This executes the checked-in controller code only. No model fragment is present.
    exec(CREATE_SCAFFOLD, namespace)
    engine = namespace["_engine"]
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE members (id INT, user_id INT, project_id INT)")
            conn.exec_driver_sql("CREATE TABLE member_roles (member_id INT, role_id INT)")
            conn.exec_driver_sql("CREATE TABLE roles (id INT, permissions TEXT)")
            conn.exec_driver_sql("INSERT INTO members VALUES (1, 2, 3), (2, 2, 4)")
            conn.exec_driver_sql("INSERT INTO member_roles VALUES (1, 1), (1, 2), (2, 3)")
            conn.exec_driver_sql(
                "INSERT INTO roles VALUES (?, ?), (?, ?), (?, ?)",
                (
                    1,
                    "---\n- :view_issues\n- :add_issues_extra\n",
                    2,
                    "---\n- :edit_issues\n",
                    3,
                    "---\n- :add_issues\n",
                ),
            )
        permissions = namespace["project_permissions"]
        assert permissions(2, 3) == {"view_issues", "add_issues_extra", "edit_issues"}
        assert permissions(2, 4) == {"add_issues"}
        assert permissions(9, 3) == set()
    finally:
        engine.dispose()


def test_sync_create_adapter_decodes_request_and_calls_handler_off_event_loop(monkeypatch):
    from threading import get_ident

    from fastapi.testclient import TestClient

    from legacylift.modernization.scaffold import CREATE_SCAFFOLD, create_interface_findings

    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    namespace = {}
    exec(CREATE_SCAFFOLD, namespace)
    caller_threads = []
    loop_threads = []
    original_dispatch = namespace["run_in_threadpool"]

    async def observed_dispatch(function, *args):
        loop_threads.append(get_ident())
        return await original_dispatch(function, *args)

    def handler(api_key, payload, base_url):
        caller_threads.append(get_ident())
        return namespace["JSONResponse"]({"key": api_key, "body": payload, "base_url": base_url})

    namespace["create_issue"] = handler
    namespace["run_in_threadpool"] = observed_dispatch
    try:
        with TestClient(namespace["app"]) as client:
            result = client.post(
                "/issues.json", json={"issue": {}}, headers={"X-Redmine-API-Key": "synthetic"}
            )
            malformed = client.post("/issues.json", content="{")
        assert result.json() == {
            "key": "synthetic",
            "body": {"issue": {}},
            "base_url": "http://testserver/",
        }
        assert malformed.json()["body"] is None
        assert len(caller_threads) == len(loop_threads) == 2
        assert all(left != right for left, right in zip(caller_threads, loop_threads, strict=True))
    finally:
        namespace["_engine"].dispose()
    old = "async def create_issue(request):\n    return None\n"
    direct = (
        "def create_issue(api_key, payload, base_url):\n    return engine.execute('SELECT 1')\n"
    )
    assert create_interface_findings(CREATE_SCAFFOLD, old)[0]["rule"] == "create_handler_signature"
    findings = create_interface_findings(CREATE_SCAFFOLD, direct)
    assert {item["rule"] for item in findings} == {"create_handler_integration"}


@pytest.mark.parametrize(
    "expression",
    [
        "read_one('SELECT id FROM users WHERE id=?', (api_key,))",
        "read_many('SELECT id FROM users WHERE id=?', params=[api_key])",
        "write(conn, 'UPDATE issues SET subject=?', [payload])",
    ],
)
def test_create_positional_helper_parameters_are_rejected_before_replay(expression):
    from legacylift.modernization.scaffold import CREATE_SCAFFOLD, create_interface_findings

    fragment = f"def create_issue(api_key, payload, base_url):\n    return {expression}\n"
    finding = create_interface_findings(CREATE_SCAFFOLD, fragment)[0]
    assert finding["rule"] == "create_helper_parameters"
    assert finding["line"] == CREATE_SCAFFOLD.count("\n") + 2
    assert "parameter dict" in finding["message"]
    valid = fragment.replace(expression, "read_one('SELECT id FROM users WHERE id=:id', {'id': 1})")
    assert create_interface_findings(CREATE_SCAFFOLD, valid) == []


def test_preflight_binds_the_actual_callable_contract_without_evaluating_source(tmp_path):
    from legacylift.modernization.scaffold import CREATE_SCAFFOLD, create_interface_findings

    optional = "def create_issue(api_key, payload, base_url, request=None):\n    return None\n"
    assert create_interface_findings(CREATE_SCAFFOLD, optional) == []
    required = optional.replace("request=None", "request")
    assert (
        create_interface_findings(CREATE_SCAFFOLD, required)[0]["rule"]
        == "create_handler_signature"
    )
    missing = "def create_issue(api_key, payload, base_url):\n    return request.headers\n"
    findings = create_interface_findings(CREATE_SCAFFOLD, missing)
    assert findings[0]["rule"] == "create_undefined_global"
    assert "request" in findings[0]["message"]
    assert findings[0]["line"] == CREATE_SCAFFOLD.count("\n") + 2
    duplicate = (
        "def create_issue(api_key, payload, base_url):\n"
        "    with transaction() as conn:\n"
        "        write(conn, 'SELECT 1', {}, conn=conn)\n"
    )
    assert (
        create_interface_findings(CREATE_SCAFFOLD, duplicate)[0]["rule"]
        == "create_helper_signature"
    )
    assert create_interface_findings(CREATE_SCAFFOLD, duplicate.replace(", conn=conn)", ")")) == []
    marker = tmp_path / "not-executed"
    inert = f"Path({str(marker)!r}).write_text('must not run')\n" + optional
    create_interface_findings(CREATE_SCAFFOLD, inert)
    assert not marker.exists()


def test_global_preflight_respects_local_variables_and_nested_closures():
    from legacylift.modernization.scaffold import CREATE_SCAFFOLD, create_interface_findings

    source = (
        "def create_issue(api_key, payload, base_url):\n"
        "    request = payload\n"
        "    def nested():\n"
        "        return request\n"
        "    return nested()\n"
    )
    assert create_interface_findings(CREATE_SCAFFOLD, source) == []


def test_preflight_explains_null_body_in_a_direct_bodyless_error_response():
    from legacylift.modernization.scaffold import CREATE_SCAFFOLD, create_interface_findings

    source = (
        "def create_issue(api_key, payload, base_url):\n"
        "    return JSONResponse(status_code=401, content=None)\n"
    )
    finding = create_interface_findings(CREATE_SCAFFOLD, source)[0]
    assert finding["rule"] == "create_bodyless_response"
    assert "null body" in finding["message"]
    assert (
        create_interface_findings(CREATE_SCAFFOLD, source.replace("JSONResponse", "Response")) == []
    )


@pytest.mark.parametrize("echo_style", [None, "objects", "quotes"])
def test_create_pipeline_reviews_assembled_file_and_preserves_fragment(
    tmp_path, monkeypatch, echo_style
):
    from legacylift.modernization import pipeline
    from legacylift.modernization.generation import GeneratedMigration
    from legacylift.modernization.scaffold import CREATE_SCAFFOLD, create_scaffold_binding

    context = {
        "workflow": "create",
        "condition": "hybrid",
        "source_assembly": create_scaffold_binding(),
    }
    fragment = {
        "objects": (
            '{"evidence_id":"runtime:create.basic","steps":[]},\n'
            '{"evidence_id":"route:create","method":"POST","path":"/issues.json"},\n'
        ),
        "quotes": '"format.api do"\n"runtime:create.basic"\n',
        None: "def create_issue(api_key, payload, base_url):\n    return None\n",
    }[echo_style]
    expected = CREATE_SCAFFOLD + fragment
    monkeypatch.setattr(pipeline, "build_context", lambda *args: context)
    monkeypatch.setattr(
        pipeline,
        "generate",
        lambda *args, **kwargs: (
            GeneratedMigration(summary="Synthetic", source=fragment, evidence_ids=[], unknowns=[]),
            {"provider": "groq", "prompt_sha256": canonical_hash(args[0])},
        ),
    )

    def review(source):
        assert source == expected
        return {"status": "static_review_passed", "findings": []}

    def verify(source, *args, **kwargs):
        assert echo_style is None
        assert source == expected
        assert kwargs["split"] == "guidance"
        return {"status": "passed", "passed_count": 6, "scenario_count": 6}

    monkeypatch.setattr(pipeline, "review_source", review)
    monkeypatch.setattr(pipeline, "evaluate_source", verify)
    run = pipeline.migrate(tmp_path, workflow="create", condition="hybrid", max_repairs=0)
    record = run["attempts"][0]
    directory = tmp_path / "runs" / run["run_id"]
    assert (directory / "fragment-0.py").read_text(encoding="utf-8") == fragment
    assert record["source_assembly"]["fragment_sha256"] == canonical_hash(fragment)
    assert record["source_sha256"] == canonical_hash(expected)
    if echo_style is not None:
        assert run["status"] == "static_review_blocked"
        assert record["review"]["findings"][0]["rule"] == "fragment_echoed_evidence"
        regenerated = prepare_prompt(context, previous=expected)
        assert regenerated["response_format"] == "implementation_lines"
        assert "copied input evidence" in regenerated["prompt"]


def test_read_scaffold_maps_all_routes_and_authenticates_api_tokens(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from legacylift.modernization.scaffold import READ_SCAFFOLD, create_interface_findings

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    namespace = {}
    exec(READ_SCAFFOLD, namespace)
    engine = namespace["_engine"]
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE tokens (value TEXT, action TEXT, user_id INT)")
            connection.exec_driver_sql("CREATE TABLE users (id INT, login TEXT)")
            connection.exec_driver_sql("INSERT INTO users VALUES (5, 'demo')")
            connection.exec_driver_sql("INSERT INTO tokens VALUES ('api', 'api', 5)")
            connection.exec_driver_sql("INSERT INTO tokens VALUES ('reset', 'recovery', 5)")

        def read_issue(key, issue_id, include):
            actor = namespace["actor_for_key"](key)
            return {"actor": actor["login"] if actor else None, "id": issue_id, "include": include}

        namespace.update(
            read_issue=read_issue,
            create_issue=lambda key, payload, base: [key, payload, base],
            update_issue=lambda key, issue_id, payload: [key, issue_id, payload],
        )
        with TestClient(namespace["app"]) as client:
            headers = {"X-Redmine-API-Key": "api"}
            read = client.get("/issues/9.json?include=journals", headers=headers)
            assert read.json() == {"actor": "demo", "id": 9, "include": "journals"}
            reset = client.get("/issues/9.json", headers={"X-Redmine-API-Key": "reset"})
            assert reset.json()["actor"] is None
            assert reset.json()["include"] == ""
            payload = {"issue": {"subject": "Nested"}, "subject": "Ignore outer field"}
            created = client.post("/issues.json", json=payload, headers=headers)
            assert created.json() == ["api", {"subject": "Nested"}, "http://testserver/"]
            updated = client.put("/issues/9.json", json=payload, headers=headers)
            assert updated.json() == ["api", 9, {"subject": "Nested"}]
            updated = client.put("/issues/9.json", content="{", headers=headers)
            assert updated.json() == ["api", 9, None]
            missing = client.post("/issues.json", json={"issue": []}, headers=headers)
            assert missing.json() == ["api", None, "http://testserver/"]
            fmt = namespace["iso_utc"]
            assert fmt("2026-01-15 12:00:00") == "2026-01-15T12:00:00Z"
            assert fmt("2026-01-15T13:00:00+01:00") == "2026-01-15T12:00:00Z"
            assert fmt(None) is None
    finally:
        engine.dispose()

    fragment = (
        "def read_issue(api_key, issue_id, include):\n    return actor_for_key(api_key)\n"
        "def create_issue(api_key, payload, base_url):\n    return None\n"
    )
    finding = create_interface_findings(READ_SCAFFOLD, fragment)[0]
    assert finding["rule"] == "read_handler_signature"
    assert "update_issue" in finding["message"]
    fragment += "def update_issue(api_key, issue_id, payload):\n    return None\n"
    assert create_interface_findings(READ_SCAFFOLD, fragment) == []
    fragment += "from fastapi import JSONResponse\ndef actor_for_key(api_key):\n    return None\n"
    findings = create_interface_findings(READ_SCAFFOLD, fragment)
    assert [item["rule"] for item in findings] == ["read_scaffold_override"] * 2


def test_range_repair_rejects_unseen_overlapping_and_stale_edits():
    source = "x = 1\ny = 2\nz = 3\n"
    packet = view(source, 1, 2)
    edit = SourceRangeEdit(start_line=1, end_line=2, new_lines=["a = 1"])
    with pytest.raises(ValueError, match="outside the supplied"):
        apply_source_ranges(
            source, [SourceRangeEdit(start_line=2, end_line=3, new_lines=[])], source_view=packet
        )
    with pytest.raises(ValueError, match="overlap"):
        apply_source_ranges(
            source,
            [edit, SourceRangeEdit(start_line=2, end_line=2, new_lines=["b = 1"])],
            source_view=packet,
        )
    with pytest.raises(ValueError, match="checksum"):
        apply_source_ranges(source + "# stale\n", [edit], source_view=packet)


@pytest.mark.parametrize("seeded", [False, True])
def test_reused_create_source_receives_current_interface_checks(tmp_path, monkeypatch, seeded):
    from legacylift.modernization import pipeline
    from legacylift.modernization.scaffold import (
        CREATE_SCAFFOLD,
        create_scaffold_binding,
        source_assembly_metadata,
    )

    context = {
        "workflow": "create",
        "condition": "hybrid",
        "source_assembly": create_scaffold_binding(),
    }
    fragment = "def create_issue(api_key, payload, base_url):\n    return request.url\n"
    source = CREATE_SCAFFOLD + fragment
    saved = tmp_path / "runs" / "saved"
    saved.mkdir(parents=True)
    record = {
        "attempt": 0,
        "source_sha256": canonical_hash(source),
        "source_assembly": source_assembly_metadata(CREATE_SCAFFOLD, fragment),
        "review": {"status": "static_review_passed", "findings": []},
        "evidence_ids": [],
        "provenance": {},
    }
    (saved / "draft-0.py").write_text(source, encoding="utf-8")
    (saved / "fragment-0.py").write_text(fragment, encoding="utf-8")
    original_record = json.dumps(record)
    (saved / "draft-0.json").write_text(original_record, encoding="utf-8")
    if seeded:
        (saved / "result.json").write_text(
            json.dumps(
                {
                    "workflow": "create",
                    "condition": "hybrid",
                    "status": "compatibility_failed",
                    "context_sha256": canonical_hash(context),
                    "attempts": [record],
                }
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr(pipeline, "build_context", lambda *args: context)
    monkeypatch.setattr(pipeline, "generate", lambda *args, **kw: pytest.fail("No request needed"))
    monkeypatch.setattr(
        pipeline, "evaluate_source", lambda *args, **kw: pytest.fail("Must block before replay")
    )
    monkeypatch.setattr(
        pipeline, "review_source", lambda source: {"status": "static_review_passed", "findings": []}
    )
    run = pipeline.migrate(
        tmp_path,
        workflow="create",
        condition="hybrid",
        max_repairs=0,
        run_id="reseeded" if seeded else "saved",
        **({"seed_run_id": "saved"} if seeded else {}),
    )
    assert run["status"] == "static_review_blocked"
    assert run["attempts"][0]["review"]["findings"][0]["rule"] == "create_undefined_global"
    assert (saved / "draft-0.json").read_text(encoding="utf-8") == original_record
    actual_review = json.loads(
        (tmp_path / "runs" / run["run_id"] / "execution-review-0.json").read_text()
    )
    assert actual_review["status"] == "blocked"


def test_invalid_repair_preserves_raw_patch_and_retries_the_valid_base(tmp_path, monkeypatch):
    from itertools import count

    from legacylift.modernization import pipeline
    from legacylift.modernization.generation import GeneratedMigration, GeneratedRangeRepair

    context = {"workflow": "update", "condition": "hybrid"}
    initial = "value = 1\n"
    invalid = "    value = 2\n"
    final = "value = 3\n"
    prompts = []
    ticks = count(1000, 100)
    monkeypatch.setattr(pipeline.time, "time", lambda: next(ticks))
    monkeypatch.setattr(pipeline, "build_context", lambda *args: context)

    def generate(prompt, **kwargs):
        prompts.append(prompt)
        if len(prompts) == 1:
            draft = GeneratedMigration(
                summary="Control", source=initial, evidence_ids=[], unknowns=[]
            )
        else:
            draft = GeneratedRangeRepair(
                summary="Patch",
                line_edits=[
                    SourceRangeEdit(
                        start_line=1,
                        end_line=1,
                        new_lines=["    value = 2" if len(prompts) == 2 else "value = 3"],
                    )
                ],
                evidence_ids=[],
                unknowns=[],
            )
        return draft, {"provider": "groq", "prompt_sha256": canonical_hash(prompt)}

    def review(source):
        return {
            "status": "blocked" if source == invalid else "static_review_passed",
            "findings": [{"rule": "invalid_python", "line": 1, "message": "unexpected indent"}]
            if source == invalid
            else [],
        }

    def evaluate(source, *args, **kwargs):
        assert source != invalid  # The rejected repair never executes.
        return {
            "status": "passed" if source == final else "compatibility_failed",
            "passed_count": 1 if source == final else 0,
            "scenario_count": 1,
            "results": [
                {
                    "scenario_id": "guidance.control",
                    "passed": source == final,
                    "mismatches": []
                    if source == final
                    else [
                        {
                            "path": "response.json.value",
                            "expected": 3,
                            "actual": 1,
                        }
                    ],
                }
            ],
        }

    monkeypatch.setattr(pipeline, "generate", generate)
    monkeypatch.setattr(pipeline, "review_source", review)
    monkeypatch.setattr(pipeline, "evaluate_source", evaluate)
    result = pipeline.migrate(tmp_path, workflow="update", condition="hybrid", max_repairs=2)
    directory = tmp_path / "runs" / result["run_id"]
    assert result["status"] == "passed"
    assert (directory / "draft-1.py").read_text() == invalid
    assert (directory / "app.py").read_text() == final
    rollback = json.loads((directory / "repair-rollback-1.json").read_text())
    assert rollback["next_repair_base_sha256"] == canonical_hash(initial)
    assert rollback["rejected_draft_sha256"] == canonical_hash(invalid)
    view = json.loads((directory / "source-view-2.json").read_text())
    assert view["source_sha256"] == canonical_hash(initial)
    assert '[1,"value = 1"]' in prompts[2]
    assert '"expected":3' in prompts[2]
    assert "Regenerate from evidence below" not in prompts[2]
    call = json.loads((directory / "call-2.json").read_text())
    assert call["repair_base_sha256"] == canonical_hash(initial)
