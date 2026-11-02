"""Container smoke-test candidate; this is not an LLM-generated result."""

from legacylift.reconstructed_app import create_app as create_baseline_app


def create_app(test_config: dict | None = None):
    return create_baseline_app(test_config)
