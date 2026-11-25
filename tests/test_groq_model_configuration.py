"""Model selection must use supported wire settings and preserve request provenance."""

import json

import httpx
import pytest

from legacylift.modernization.generation import (
    GROQ_MODEL,
    GROQ_QWEN_MODEL,
    READ_IMPLEMENTATION_PROTOCOL,
    generate,
)


@pytest.mark.parametrize("effort", [None, "medium"])
def test_read_handler_response_preserves_original_and_builds_the_three_bodies(monkeypatch, effort):
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")
    monkeypatch.setenv("LEGACYLIFT_GROQ_MODEL", GROQ_MODEL)
    wire_response = json.dumps(
        {
            "summary": "Synthetic bodies",
            "evidence_ids": ["source:read"],
            "unknowns": [],
            "helper_lines": [],
            "read_body": ["if not api_key:", "    return Response(status_code=401)", "return None"],
            "create_body": ["return None"],
            "update_body": ["return None"],
        }
    )

    def respond(request):
        body = json.loads(request.content)
        schema = body["response_format"]["json_schema"]["schema"]
        assert set(schema["required"]) == set(json.loads(wire_response))
        assert body["max_completion_tokens"] == 4000
        assert body["reasoning_effort"] == (effort or "low")
        assert schema["properties"]["evidence_ids"]["items"]["enum"] == ["source:read"]
        return httpx.Response(200, json={"choices": [{"message": {"content": wire_response}}]})

    draft, provenance = generate(
        'Return three handler bodies.\nEVIDENCE_JSON:\n{"source":[{"evidence_id":"source:read"}]}',
        provider="groq",
        response_format="read_handlers",
        groq_reasoning_effort=effort,
        transport=httpx.MockTransport(respond),
    )
    assert provenance["implementation_protocol"] == READ_IMPLEMENTATION_PROTOCOL
    assert provenance["reasoning_effort"] == (effort or "low")
    assert provenance["raw_structured_response"] == wire_response
    assert (
        "def read_issue(api_key, issue_id, include):\n"
        "    if not api_key:\n        return Response(status_code=401)\n"
        "    return None\n"
    ) in draft.source
    assert "def create_issue(api_key, payload, base_url):" in draft.source
    assert "def update_issue(api_key, issue_id, payload):" in draft.source
    compile(draft.source, "<model-fragment>", "exec")


@pytest.mark.parametrize("model", [GROQ_MODEL, GROQ_QWEN_MODEL])
def test_supported_model_settings_reach_transport_and_reservation(monkeypatch, model):
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")
    monkeypatch.setenv("LEGACYLIFT_GROQ_MODEL", model)
    requests, reservations = [], []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Synthetic generation",
                                    "source": "app = object()\n",
                                    "evidence_ids": [],
                                    "unknowns": [],
                                }
                            )
                        },
                    }
                ],
                "usage": {"total_tokens": 1},
            },
        )

    _, provenance = generate(
        "prompt",
        provider="groq",
        transport=httpx.MockTransport(respond),
        before_request=lambda provider, selected: reservations.append((provider, selected)),
    )
    request = requests[0]
    assert request["model"] == provenance["model"] == model
    assert request["temperature"] == provenance["temperature"]
    assert request["reasoning_effort"] == provenance["reasoning_effort"]
    assert reservations == [("groq", model)]
    if model == GROQ_QWEN_MODEL:
        assert request["max_completion_tokens"] == 16384
        assert request["reasoning_effort"] == "none"
        assert request["temperature"] == 0.7
        assert request["reasoning_format"] == "hidden"
        assert "include_reasoning" not in request
    else:
        assert request["max_completion_tokens"] == 65536
        assert request["reasoning_effort"] == "medium"
        assert request["temperature"] == 0
        assert request["include_reasoning"] is False
        assert "reasoning_format" not in request
    for name, value in provenance["model_request_parameters"].items():
        assert request[name] == value


def test_unsupported_model_stops_before_reservation_or_http(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")
    monkeypatch.setenv("LEGACYLIFT_GROQ_MODEL", "unsupported/model")
    with pytest.raises(ValueError, match="unsupported Groq"):
        generate(
            "prompt",
            provider="groq",
            transport=httpx.MockTransport(lambda request: pytest.fail("unexpected HTTP call")),
            before_request=lambda *args: pytest.fail("unexpected reservation"),
        )


def test_default_model_is_retained_without_override(monkeypatch):
    from legacylift.modernization.generation import configured_groq_model

    monkeypatch.delenv("LEGACYLIFT_GROQ_MODEL", raising=False)
    assert configured_groq_model() == GROQ_MODEL


@pytest.mark.parametrize("provider", ["groq", "gemini"])
@pytest.mark.parametrize("citation", ["source:one", "invented:one"])
def test_citations_are_constrained_to_outbound_ids_and_validated_after_transport(
    monkeypatch, provider, citation
):
    from legacylift.modernization.generation import ProviderFailure

    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    prompt = 'Generate JSON.\nEVIDENCE_JSON:\n{"source":[{"evidence_id":"source:one"}]}'
    content = json.dumps(
        {
            "summary": "Synthetic",
            "source": "app = None\n",
            "evidence_ids": [citation],
            "unknowns": [],
        }
    )

    def respond(request):
        payload = json.loads(request.content)
        schema = (
            payload["response_format"]["json_schema"]["schema"]
            if provider == "groq"
            else payload["generationConfig"]["responseSchema"]
        )
        assert schema["properties"]["evidence_ids"]["items"]["enum"] == ["source:one"]
        body = (
            {"choices": [{"message": {"content": content}}]}
            if provider == "groq"
            else {"candidates": [{"content": {"parts": [{"text": content}]}}]}
        )
        return httpx.Response(200, json=body)

    if citation == "invented:one":
        with pytest.raises(ProviderFailure) as error:
            generate(prompt, provider=provider, transport=httpx.MockTransport(respond))
        assert error.value.attempts[0]["category"] == "invalid_model_output"
    else:
        _, provenance = generate(prompt, provider=provider, transport=httpx.MockTransport(respond))
        assert len(provenance["response_schema_sha256"]) == 64


def test_repair_schema_ids_are_read_from_its_json_before_source_blocks():
    from legacylift.modernization.generation import _prompt_evidence_ids

    prompt = (
        'Repair.\nREPAIR_CONTEXT_JSON:\n{"allowed_evidence_ids":["b","a","b"]}'
        "\nPREVIOUS_SOURCE:\nnot JSON"
    )
    assert _prompt_evidence_ids(prompt) == ["a", "b"]


def test_gemini_repairs_use_separated_instructions_and_deeper_reasoning(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic")
    monkeypatch.delenv("LEGACYLIFT_GEMINI_MODEL", raising=False)
    directive = "Repair only the permitted range."
    data = 'REPAIR_CONTEXT_JSON:\n{"allowed_evidence_ids":["source:one"]}'

    def respond(request):
        body = json.loads(request.content)
        assert directive in body["systemInstruction"]["parts"][0]["text"]
        assert body["contents"] == [{"parts": [{"text": data}]}]
        assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "medium"}
        assert body["generationConfig"]["maxOutputTokens"] == 12_000
        result = {
            "summary": "Synthetic",
            "evidence_ids": ["source:one"],
            "unknowns": [],
            "line_edits": [{"start_line": 1, "end_line": 1, "new_lines": ["pass"]}],
        }
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(result)}]}}]}
        )

    generate(
        directive + "\n" + data,
        provider="gemini",
        response_format="line_edits",
        transport=httpx.MockTransport(respond),
    )


@pytest.mark.parametrize("provider", ["groq", "gemini"])
@pytest.mark.parametrize("response_format", ["source_lines", "implementation_lines"])
def test_line_response_reassembles_indentation_without_decoding_python_strings(
    monkeypatch, provider, response_format
):
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    lines = ["def example():", r'    return "line\nbreak"', "", "app = object()"]
    content = json.dumps(
        {"summary": "Test lines", response_format: lines, "evidence_ids": [], "unknowns": []}
    )
    instructions = "Return the generated Python handler."
    evidence = 'EVIDENCE_JSON:\n{"source":[{"text":"untrusted excerpt"}]}'

    def respond(request):
        payload = json.loads(request.content)
        if provider == "groq":
            schema = payload["response_format"]["json_schema"]["schema"]
            assert payload["max_completion_tokens"] == 4000
            assert payload["reasoning_effort"] == "low"
            if response_format in {"implementation_lines", "source_lines"}:
                system, data = payload["messages"]
                assert system["role"] == "system" and instructions in system["content"]
                assert "untrusted excerpt" not in system["content"]
                assert data == {"role": "user", "content": evidence}
            choices = [{"message": {"content": content}}]
            response = {"choices": choices}
        else:
            schema = payload["generationConfig"]["responseSchema"]
            if response_format in {"implementation_lines", "source_lines"}:
                system = payload["systemInstruction"]["parts"][0]["text"]
                assert instructions in system and "untrusted excerpt" not in system
                assert payload["contents"] == [{"parts": [{"text": evidence}]}]
            response = {"candidates": [{"content": {"parts": [{"text": content}]}}]}
        assert schema["properties"][response_format]["type"].lower() == "array"
        assert response_format in schema["required"]
        assert "source" not in schema["properties"]
        return httpx.Response(200, json=response)

    draft, provenance = generate(
        f"{instructions}\n{evidence}",
        provider=provider,
        response_format=response_format,
        transport=httpx.MockTransport(respond),
    )
    assert draft.source == "\n".join(lines) + "\n"
    if response_format in {"implementation_lines", "source_lines"}:
        from legacylift.modernization.contracts import canonical_hash

        assert provenance["user_evidence_sha256"] == canonical_hash(evidence)


def test_numbered_repairs_use_the_shared_provider_schema(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")
    edit = {"start_line": 3, "end_line": 3, "new_lines": ["    row = result.mappings().first()"]}
    content = json.dumps(
        {"summary": "Fix row access", "line_edits": [edit], "evidence_ids": [], "unknowns": []}
    )

    def respond(request):
        payload = json.loads(request.content)
        schema = payload["response_format"]["json_schema"]["schema"]
        fields = schema["properties"]["line_edits"]["items"]
        assert fields["required"] == ["start_line", "end_line", "new_lines"]
        assert fields["additionalProperties"] is False
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    draft, _ = generate(
        "prompt",
        provider="groq",
        response_format="line_edits",
        transport=httpx.MockTransport(respond),
    )
    assert draft.line_edits[0].model_dump() == edit
