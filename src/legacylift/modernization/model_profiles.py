"""Versioned evidence/output budgets for explicitly selected larger-context services."""

GEMINI_PROFILE = "gemini-free-v1"
OPENROUTER_PROFILE = "openrouter-free-v1"
LARGE_PROFILES = frozenset({GEMINI_PROFILE, OPENROUTER_PROFILE})
PROMPT_BYTE_LIMIT = 48_000
RUNTIME_BYTE_BUDGET = 26_000
SOURCE_BYTE_BUDGET = 12_000
MAX_COMPLETION_TOKENS = 12_000


def for_provider(provider: str) -> str | None:
    return {"gemini": GEMINI_PROFILE, "openrouter": OPENROUTER_PROFILE}.get(provider)
