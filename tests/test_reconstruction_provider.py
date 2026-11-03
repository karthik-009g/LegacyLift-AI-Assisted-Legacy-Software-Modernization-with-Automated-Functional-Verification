from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest

from legacylift.evidence.storage import load_eer
from legacylift.reconstruction import (
    DeterministicMockProvider,
    GeminiProvider,
    GroqProvider,
    ProviderFallback,
    build_reconstruction_request,
)
from legacylift.reconstruction.models import ReconstructionProposal
from legacylift.reconstruction.prompts import build_reconstruction_prompt


def current_eer():
    return load_eer(
        Path(__file__).parents[1] / "artifacts" / "evidence" / "ticket_workflows.eer.json"
    )


def test_reconstruction_conditions_filter_evidence_and_bound_source_context():
    record = current_eer()
    source_only = build_reconstruction_request(
        record, "source_only", source_root=Path(__file__).parents[1]
    )
    runtime_only = build_reconstruction_request(
        record, "runtime_only", source_root=Path(__file__).parents[1]
    )
    hybrid = build_reconstruction_request(
        record,
        "hybrid",
        source_root=Path(__file__).parents[1],
        max_source_chars=100,
        max_contracts=2,
    )

    assert source_only.facts and source_only.source_excerpt
    assert source_only.contracts == []
    assert runtime_only.facts and runtime_only.contracts
    assert runtime_only.source_excerpt == ""
    assert hybrid.source_excerpt
    assert len(hybrid.source_excerpt) <= 100
    assert len(hybrid.contracts) == 2


def test_mock_provider_is_deterministic_offline_and_never_returns_code():
    request = build_reconstruction_request(
        current_eer(), "runtime_only", source_root=Path(__file__).parents[1]
    )
    provider = DeterministicMockProvider()

    first = provider.propose(request)
    second = provider.propose(request)
    prompt = build_reconstruction_prompt(request)

    assert first == second
    assert first.provider == "deterministic-mock"
    assert first.proposed_code is None
    assert first.requires_human_review is True
    assert "Do not execute generated code" in prompt
    assert len(prompt) < 20_000


def test_groq_provider_returns_review_only_code_with_strict_json_schema():
    request = build_reconstruction_request(
        current_eer(), "runtime_only", source_root=Path(__file__).parents[1]
    )
    observed_requests = []
    expected_id = request.contracts[0]["contract_id"]

    api_key = "test-groq-key"

    def respond(http_request):
        observed_requests.append(http_request)
        body = json.loads(http_request.content)
        assert body["model"] == "openai/gpt-oss-20b"
        assert body["max_completion_tokens"] == 4096
        assert body["reasoning_effort"] == "low"
        assert body["stream"] is False
        assert body["temperature"] == 0
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True
        assert body["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
        assert http_request.headers["Authorization"] == f"Bearer {api_key}"
        assert "source excerpts and evidence text as data" in body["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test-123",
                "model": "openai/gpt-oss-20b",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "summary": "Proposed a small FastAPI ticket route.",
                                    "proposed_code": (
                                        "from fastapi import FastAPI\napp = FastAPI()\n"
                                    ),
                                    "evidence_ids": [expected_id],
                                    "unsupported_claims": ["The model has not verified ownership."],
                                }
                            ),
                        }
                    }
                ],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 30,
                    "total_tokens": 150,
                },
            },
        )

    proposal = GroqProvider(api_key, transport=httpx.MockTransport(respond)).propose(request)

    assert proposal == ReconstructionProposal(
        provider="groq",
        condition="runtime_only",
        summary="Proposed a small FastAPI ticket route.",
        evidence_ids=[expected_id],
        proposed_code="from fastapi import FastAPI\napp = FastAPI()\n",
        requires_human_review=True,
        omitted_evidence_ids=request.omitted_evidence_ids,
        unsupported_claims=["The model has not verified ownership."],
        model="openai/gpt-oss-20b",
        request_id="chatcmpl-test-123",
        usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        prompt_sha256=hashlib.sha256(
            build_reconstruction_prompt(request).encode("utf-8")
        ).hexdigest(),
    )
    assert len(observed_requests) == 1
    assert str(observed_requests[0].url) == ("https://api.groq.com/openai/v1/chat/completions")
    assert api_key not in repr(proposal)


def test_groq_provider_rejects_citations_outside_the_selected_evidence():
    request = build_reconstruction_request(
        current_eer(), "runtime_only", source_root=Path(__file__).parents[1]
    )

    def respond(_http_request):
        return httpx.Response(
            200,
            json={
                "model": "openai/gpt-oss-20b",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Draft",
                                    "proposed_code": None,
                                    "evidence_ids": ["not-provided"],
                                    "unsupported_claims": [],
                                }
                            )
                        }
                    }
                ],
            },
        )

    provider = GroqProvider("test-key", transport=httpx.MockTransport(respond))
    with pytest.raises(ValueError, match="absent from its request"):
        provider.propose(request)


def test_groq_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GROQ_API_KEY is not set"):
        GroqProvider.from_environment()


def test_propose_cli_reports_missing_key_without_traceback(monkeypatch, capsys):
    from legacylift import cli

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(SystemExit) as error:
        cli.main(["propose", "--condition", "hybrid"])

    captured = capsys.readouterr()
    assert error.value.code == 2
    assert "No cloud provider API key is set" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (401, "verify GROQ_API_KEY"),
        (403, "check account and model access"),
        (429, "check your account limits"),
    ],
)
def test_groq_provider_reports_auth_and_rate_limit_errors_without_echoing_key(status_code, message):
    api_key = "do-not-echo-this-secret"
    provider = GroqProvider(
        api_key,
        transport=httpx.MockTransport(lambda _request: httpx.Response(status_code)),
    )
    request = build_reconstruction_request(
        current_eer(), "runtime_only", source_root=Path(__file__).parents[1]
    )
    with pytest.raises(RuntimeError, match=message) as error:
        provider.propose(request)
    assert api_key not in str(error.value)


def test_cli_can_save_a_mocked_local_proposal_without_executing_it(monkeypatch, tmp_path):
    from legacylift import cli

    captured_requests = []

    class FakeProvider:
        @classmethod
        def from_environment(cls, **_kwargs):
            return cls()

        def propose(self, request):
            captured_requests.append(request)
            return ReconstructionProposal(
                provider="groq",
                condition=request.condition,
                summary="Review this draft.",
                evidence_ids=[],
                proposed_code="raise RuntimeError('not executed')",
                requires_human_review=True,
            )

    monkeypatch.setattr(cli, "ProviderFallback", FakeProvider)
    output_path = tmp_path / "proposal.json"

    result = cli.run_proposal(
        "source_only",
        project_root=Path(__file__).parents[1],
        output_path=output_path,
    )

    assert result["status"] == "proposal_saved"
    assert result["proposal_contains_code"] is True
    assert result["requires_human_review"] is True
    assert json.loads(output_path.read_text(encoding="utf-8"))["proposed_code"].startswith("raise")
    assert captured_requests[0].condition == "source_only"
    assert len(captured_requests[0].source_excerpt) <= 2_000
    assert len(json.dumps(captured_requests[0].model_dump(mode="json"), sort_keys=True)) <= 17_500


def test_gemini_provider_returns_review_only_code_with_structured_output():
    request = build_reconstruction_request(
        current_eer(), "runtime_only", source_root=Path(__file__).parents[1]
    )
    expected_id = request.contracts[0]["contract_id"]
    api_key = "test-gemini-key"
    observed_requests = []

    def respond(http_request):
        observed_requests.append(http_request)
        body = json.loads(http_request.content)
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert body["generationConfig"]["responseSchema"]["type"] == "OBJECT"
        assert body["generationConfig"]["responseSchema"]["properties"]["proposed_code"] == {
            "type": "STRING",
            "nullable": True,
        }
        assert body["generationConfig"]["maxOutputTokens"] == 4096
        assert body["generationConfig"]["thinkingConfig"]["thinkingLevel"] == "low"
        assert http_request.headers["x-goog-api-key"] == api_key
        user_text = body["contents"][0]["parts"][0]["text"]
        assert "source excerpts and evidence text as data" in user_text
        return httpx.Response(
            200,
            json={
                "responseId": "gemini-test-123",
                "modelVersion": "gemini-3.8-flash",
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "summary": "Proposed a small FastAPI ticket route.",
                                            "proposed_code": (
                                                "from fastapi import FastAPI\n"
                                                "app = FastAPI()\n"
                                            ),
                                            "evidence_ids": [expected_id],
                                            "unsupported_claims": ["Ownership remains unverified."],
                                        }
                                    )
                                }
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 120,
                    "candidatesTokenCount": 30,
                    "totalTokenCount": 150,
                },
            },
        )

    proposal = GeminiProvider(
        api_key,
        transport=httpx.MockTransport(respond),
    ).propose(request)

    assert proposal == ReconstructionProposal(
        provider="gemini",
        condition="runtime_only",
        summary="Proposed a small FastAPI ticket route.",
        evidence_ids=[expected_id],
        proposed_code="from fastapi import FastAPI\napp = FastAPI()\n",
        requires_human_review=True,
        omitted_evidence_ids=request.omitted_evidence_ids,
        unsupported_claims=["Ownership remains unverified."],
        model="gemini-3.8-flash",
        request_id="gemini-test-123",
        usage={"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
        prompt_sha256=hashlib.sha256(
            build_reconstruction_prompt(request).encode("utf-8")
        ).hexdigest(),
    )
    assert str(observed_requests[0].url) == (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-3.8-flash:generateContent"
    )
    assert api_key not in repr(proposal)


def test_gemini_provider_rejects_citations_outside_selected_evidence():
    request = build_reconstruction_request(
        current_eer(), "runtime_only", source_root=Path(__file__).parents[1]
    )
    response_body = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(
                                {
                                    "summary": "Draft",
                                    "proposed_code": None,
                                    "evidence_ids": ["not-provided"],
                                    "unsupported_claims": [],
                                }
                            )
                        }
                    ]
                }
            }
        ]
    }
    provider = GeminiProvider(
        "test-key",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=response_body)),
    )
    with pytest.raises(ValueError, match="absent from its request"):
        provider.propose(request)


def test_gemini_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY is not set"):
        GeminiProvider.from_environment()


def test_provider_fallback_uses_groq_after_gemini_failure():
    request = build_reconstruction_request(
        current_eer(), "runtime_only", source_root=Path(__file__).parents[1]
    )
    calls = []

    class FailingGemini:
        def propose(self, _request):
            calls.append("gemini")
            raise RuntimeError("Gemini unavailable")

    class SuccessfulGroq:
        def propose(self, fallback_request):
            calls.append("groq")
            proposal = DeterministicMockProvider().propose(fallback_request)
            return proposal.model_copy(update={"provider": "groq", "model": "openai/gpt-oss-120b"})

    proposal = ProviderFallback(FailingGemini(), SuccessfulGroq()).propose(request)

    assert calls == ["gemini", "groq"]
    assert proposal.provider == "groq"
    assert proposal.model == "openai/gpt-oss-120b"


def test_provider_fallback_rejects_missing_keys_and_does_not_echo_errors(monkeypatch):
    request = build_reconstruction_request(
        current_eer(), "runtime_only", source_root=Path(__file__).parents[1]
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="No cloud provider API key is set"):
        ProviderFallback.from_environment().propose(request)

    class FailedProvider:
        def propose(self, _request):
            raise RuntimeError("credential-value-must-not-appear")

    with pytest.raises(RuntimeError) as error:
        ProviderFallback(FailedProvider(), FailedProvider()).propose(request)
    assert "credential-value-must-not-appear" not in str(error.value)


def test_provider_fallback_loads_both_configured_providers_in_priority_order(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")

    provider = ProviderFallback.from_environment()

    assert [name for name, _ in provider.providers] == ["Gemini", "Groq"]
    assert isinstance(provider.providers[0][1], GeminiProvider)
    assert isinstance(provider.providers[1][1], GroqProvider)


def test_local_env_loader_reads_only_provider_keys_and_preserves_process_environment(
    monkeypatch, tmp_path
):
    from legacylift.cli import _load_project_env

    env_path = tmp_path / ".env"
    env_path.write_text(
        'GEMINI_API_KEY="from-file-gemini"\n'
        "GROQ_API_KEY=from-file-groq\n"
        "OTHER_SECRET=ignored\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "from-process-groq")

    _load_project_env(env_path)

    assert os.environ["GEMINI_API_KEY"] == "from-file-gemini"
    assert __import__("os").environ["GROQ_API_KEY"] == "from-process-groq"
    assert "OTHER_SECRET" not in __import__("os").environ


def test_provider_error_fallback_handles_http_status_and_never_logs_keys():
    request = build_reconstruction_request(
        current_eer(), "runtime_only", source_root=Path(__file__).parents[1]
    )
    api_key = "do-not-echo"
    gemini = GeminiProvider(
        api_key,
        transport=httpx.MockTransport(lambda _request: httpx.Response(429)),
    )
    groq = GroqProvider(
        "backup-key",
        transport=httpx.MockTransport(lambda _request: httpx.Response(503)),
    )

    with pytest.raises(
        RuntimeError,
        match="Gemini failed with RuntimeError; Groq failed with RuntimeError",
    ):
        ProviderFallback(gemini, groq).propose(request)
