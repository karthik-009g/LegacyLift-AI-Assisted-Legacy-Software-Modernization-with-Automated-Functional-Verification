"""Larger cloud requests must remain explicitly free and preserve trial boundaries."""

import copy
import json

import httpx
import pytest

from legacylift.modernization import openrouter
from legacylift.modernization.generation import ProviderFailure, generate


def model_card():
    return {
        "id": openrouter.FREE_MODELS[0],
        "pricing": {"prompt": "0", "completion": "0", "request": "0"},
        "context_length": 1_000_000,
        "top_provider": {"max_completion_tokens": 131_072},
        "supported_parameters": ["response_format", "structured_outputs"],
    }


def test_free_client_checks_public_catalog_before_reserving_generation(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-private-key")
    monkeypatch.delenv("LEGACYLIFT_OPENROUTER_MODEL", raising=False)
    events = []

    def respond(request):
        if request.method == "GET":
            events.append("catalog")
            assert str(request.url) == openrouter.MODELS_URL
            assert "authorization" not in request.headers
            return httpx.Response(200, json={"data": [model_card()]})
        events.append("generation")
        assert str(request.url) == openrouter.COMPLETIONS_URL
        body = json.loads(request.content)
        assert body["model"].endswith(":free")
        assert body["max_tokens"] == 12_000
        assert body["provider"]["max_price"] == {"prompt": 0, "completion": 0}
        assert body["provider"]["require_parameters"] is True
        assert body["provider"]["allow_fallbacks"] is False
        assert "reasoning_effort" not in body
        assert "max_completion_tokens" not in body
        schema = body["response_format"]["json_schema"]["schema"]
        assert schema["properties"]["evidence_ids"]["items"]["enum"] == ["source:one"]
        return httpx.Response(
            200,
            json={
                "model": openrouter.FREE_MODELS[0],
                "provider": "Synthetic endpoint",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Synthetic",
                                    "source_lines": ["app = object()"],
                                    "evidence_ids": ["source:one"],
                                    "unknowns": [],
                                }
                            )
                        },
                    }
                ],
                "usage": {"total_tokens": 30, "cost": 0},
            },
        )

    result, provenance = generate(
        'Generate JSON.\nEVIDENCE_JSON:\n{"source":[{"evidence_id":"source:one"}]}',
        provider="openrouter",
        response_format="source_lines",
        transport=httpx.MockTransport(respond),
        before_request=lambda name, model: events.append("reservation"),
    )
    assert events == ["catalog", "reservation", "generation"]
    assert result.source == "app = object()\n"
    assert provenance["free_model_preflight"]["zero_price_verified"] is True
    assert provenance["serving_provider"] == "Synthetic endpoint"
    assert "synthetic-private-key" not in json.dumps(provenance)


@pytest.mark.parametrize("fault", ["paid", "missing", "malformed", "no_schema", "short_output"])
def test_unusable_or_nonfree_catalog_blocks_before_generation_and_reservation(monkeypatch, fault):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-private-key")
    monkeypatch.delenv("LEGACYLIFT_OPENROUTER_MODEL", raising=False)
    card = model_card()
    data = {"data": [card]}
    if fault == "paid":
        card["pricing"]["completion"] = "0.1"
    elif fault == "missing":
        data["data"] = []
    elif fault == "malformed":
        card["top_provider"] = None
    elif fault == "no_schema":
        card["supported_parameters"] = ["response_format"]
    elif fault == "short_output":
        card["top_provider"]["max_completion_tokens"] = 2048

    def respond(request):
        assert request.method == "GET", "generation must not be requested"
        return httpx.Response(200, json=data)

    with pytest.raises(ProviderFailure) as error:
        generate(
            "Generate JSON",
            provider="openrouter",
            transport=httpx.MockTransport(respond),
            before_request=lambda *a: pytest.fail("generation was reserved"),
        )
    assert error.value.attempts[0]["category"] == "free_model_preflight_failed"


def test_paid_model_configuration_never_reaches_http(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic")
    monkeypatch.setenv("LEGACYLIFT_OPENROUTER_MODEL", "paid/model")
    with pytest.raises(ValueError, match="approved :free"):
        generate(
            "Generate JSON",
            provider="openrouter",
            transport=httpx.MockTransport(lambda request: pytest.fail("unexpected HTTP")),
        )


@pytest.mark.parametrize("value", ["0.01", "-0.01", "NaN", "invalid", True])
def test_nonzero_or_malformed_reported_cost_is_rejected(value):
    with pytest.raises(ValueError):
        openrouter.verify_reported_cost({"cost": value})


def test_profile_configuration_is_independent_of_credentials(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("LEGACYLIFT_OPENROUTER_MODEL", openrouter.FREE_MODELS[1])
    assert openrouter.configured_model() == openrouter.FREE_MODELS[1]
    card = copy.deepcopy(model_card())
    card["id"] = openrouter.FREE_MODELS[1]
    assert openrouter.verify_free_model({"data": [card]}, card["id"])["zero_price_verified"]
