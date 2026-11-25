import pytest


@pytest.fixture(autouse=True)
def _no_real_llm_key(monkeypatch):
    """Tests must never reach the network: strip any key loaded from .env."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
