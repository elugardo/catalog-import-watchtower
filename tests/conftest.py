"""Shared fixtures. Settings and the engine are cached per process, so every
test that changes the environment goes through `reset_caches` (directly or via
`make_client`), which clears both caches before and after the test."""

import pytest
from fastapi.testclient import TestClient

from app.db import get_engine
from app.settings import get_settings

# The real lru_cache wrappers, captured at import: a test may monkeypatch the
# module attributes (see test_oncall_stub), and teardown must still clear these.
_CACHED = (get_settings, get_engine)


def _reset_caches() -> None:
    for cached in _CACHED:
        cached.cache_clear()


@pytest.fixture
def reset_caches():
    """Clear the settings and engine caches around a test that changes the environment."""
    _reset_caches()
    yield _reset_caches
    _reset_caches()


@pytest.fixture
def make_client(monkeypatch, reset_caches):
    """Build a TestClient for a fresh app after setting environment variables.

    Usage: `client = make_client(AGENT_ENABLED="true")`.
    """

    def _make(**env: str) -> TestClient:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        reset_caches()
        from app.main import create_app

        return TestClient(create_app())

    return _make
