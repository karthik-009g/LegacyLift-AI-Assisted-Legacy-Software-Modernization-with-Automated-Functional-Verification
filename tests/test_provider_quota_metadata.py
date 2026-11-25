"""Provider quota facts must survive rejection without echoed credentials or prompts."""

import httpx
import pytest

from legacylift.modernization.generation import ProviderFailure, generate


@pytest.mark.parametrize("status", [413, 429])
def test_quota_rejection_records_dimension_and_numeric_headers_without_message(monkeypatch, status):
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status,
            headers={"x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-tokens": "12"},
            json={
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": "Limit 8000, Requested 9001 on tokens per minute for private-org. "
                    "Echoed synthetic-key and PRIVATE-PROMPT",
                }
            },
        )
    )
    with pytest.raises(ProviderFailure) as caught:
        generate("PRIVATE-PROMPT", provider="groq", transport=transport)
    attempt = caught.value.attempts[0]
    assert attempt["reported_limit_dimension"] == "tokens_per_minute"
    assert attempt["reported_token_limit"] == 8000
    assert attempt["reported_tokens_remaining"] == 12
    assert attempt["provider_error_code"] == "rate_limit_exceeded"
    assert attempt["reported_quota_limit_units"] == 8000
    assert attempt["reported_requested_units"] == 9001
    assert all(
        value not in str(attempt) for value in ("private-org", "synthetic-key", "PRIVATE-PROMPT")
    )


@pytest.mark.parametrize("body", [[], {"error": []}, {"error": {"code": {}, "message": []}}])
def test_malformed_quota_metadata_keeps_original_provider_failure(monkeypatch, body):
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")
    transport = httpx.MockTransport(lambda request: httpx.Response(413, json=body))
    with pytest.raises(ProviderFailure) as caught:
        generate("prompt", provider="groq", transport=transport)
    assert caught.value.category == "request_too_large"
    assert caught.value.attempts == [
        {"provider": "groq", "category": "request_too_large", "http_status": 413}
    ]


def test_untrusted_header_and_code_values_are_omitted(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "synthetic-key")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            429,
            headers={
                "x-ratelimit-limit-tokens": "synthetic-key",
                "x-ratelimit-remaining-tokens": "99999999999999999999",
            },
            json={"error": {"code": "synthetic-key", "message": "Unspecified error"}},
        )
    )
    with pytest.raises(ProviderFailure) as caught:
        generate("prompt", provider="groq", transport=transport)
    assert caught.value.category == "quota_exhausted"
    assert caught.value.attempts == [
        {"provider": "groq", "category": "quota_exhausted", "http_status": 429}
    ]
