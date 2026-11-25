"""Explicit zero-price models and bounded request settings for OpenRouter."""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation

from .contracts import canonical_hash
from .model_profiles import (
    MAX_COMPLETION_TOKENS,
    OPENROUTER_PROFILE,
)

MODELS_URL = "https://openrouter.ai/api/v1/models"
COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
FREE_MODELS = (
    "nvidia/nemotron-3.5-super-vl:free",
    "inclusionai/ling-3.2-flash:free",
    "baidu/ernie-5.5-flash-preview:free",
)
PROFILE = OPENROUTER_PROFILE


def configured_model() -> str:
    model = os.environ.get("LEGACYLIFT_OPENROUTER_MODEL") or FREE_MODELS[0]
    if model not in FREE_MODELS:
        raise ValueError("unsupported OpenRouter model; select an approved :free model")
    return model


def verify_free_model(catalog: dict, model: str) -> dict:
    """Fail before generation if the live catalog cannot prove the selected route is free."""
    if model not in FREE_MODELS:
        raise ValueError("OpenRouter model is not in the free-model allowlist")
    if not isinstance(catalog, dict) or not isinstance(catalog.get("data"), list):
        raise ValueError("free-model catalog is malformed")
    matches = [
        item for item in catalog["data"] if isinstance(item, dict) and item.get("id") == model
    ]
    if len(matches) != 1:
        raise ValueError("selected free model is not uniquely available in the live catalog")
    card = matches[0]
    pricing = card.get("pricing", {})
    if not isinstance(pricing, dict):
        raise ValueError("free-model prices are malformed")
    try:
        if any(Decimal(pricing[key]) != 0 for key in ("prompt", "completion")):
            raise ValueError("selected model no longer has zero token prices")
        if Decimal(pricing.get("request", "0")) != 0:
            raise ValueError("selected model has a request fee")
    except (KeyError, TypeError, InvalidOperation) as error:
        raise ValueError("free-model pricing is missing or malformed") from error
    parameters = card.get("supported_parameters", [])
    provider = card.get("top_provider", {})
    if (
        not isinstance(parameters, list)
        or not isinstance(provider, dict)
        or "structured_outputs" not in parameters
        or "response_format" not in parameters
        or type(card.get("context_length")) is not int
        or card["context_length"] < 65_536
        or type(provider.get("max_completion_tokens")) is not int
        or provider["max_completion_tokens"] < MAX_COMPLETION_TOKENS
    ):
        raise ValueError("free model lacks the required context, output or structured format")
    return {
        "model": model,
        "catalog_url": MODELS_URL,
        "card_sha256": canonical_hash(card),
        "context_length": card["context_length"],
        "max_completion_tokens": provider["max_completion_tokens"],
        "prompt_price": pricing["prompt"],
        "completion_price": pricing["completion"],
        "zero_price_verified": True,
    }


def verify_reported_cost(usage: dict) -> None:
    """Reject a returned nonzero/invalid cost instead of continuing a supposedly free trial."""
    cost = usage.get("cost")
    if cost is None:
        return
    try:
        if isinstance(cost, bool) or Decimal(str(cost)) != 0:
            raise ValueError("free-model response reported a nonzero cost")
    except InvalidOperation as error:
        raise ValueError("free-model response cost is malformed") from error


def request_parameters() -> dict:
    return {
        "max_tokens": MAX_COMPLETION_TOKENS,
        "temperature": 0,
        "provider": {
            "require_parameters": True,
            "allow_fallbacks": False,
            "max_price": {"prompt": 0, "completion": 0},
        },
    }
