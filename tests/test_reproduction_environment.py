"""Reproduction commands must not inherit model credentials or old project settings."""

import importlib.util
from pathlib import Path


def test_reproduction_environment_isolated_from_credentials_and_host_configuration(monkeypatch):
    path = Path(__file__).parents[1] / "scripts" / "reproduce_install.py"
    spec = importlib.util.spec_from_file_location("reproduction_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    names = [
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "GITHUB_TOKEN",
        "LEGACYLIFT_DATABASE_URL",
        "LEGACYLIFT_REDIS_URL",
        "LEGACYLIFT_WEB_DIST",
        "PYTHONPATH",
        "PYTHONHOME",
        "VIRTUAL_ENV",
        "PIP_EXTRA_INDEX_URL",
    ]
    for name in names:
        monkeypatch.setenv(name, "private-test-marker")
    monkeypatch.setenv("PIP_INDEX_URL", "https://private-test-marker.invalid/simple")
    cleaned = module.clean_environment()
    assert not set(names) & cleaned.keys()
    assert cleaned["PIP_INDEX_URL"] == "https://pypi.org/simple"
    assert cleaned["PYTHONNOUSERSITE"] == "1"
    assert "private-test-marker" not in str(cleaned)
