"""Shared fixtures. Settings and the engine are cached per process, so every
fixture that changes the environment clears both caches and rebuilds the app."""

import pytest
from fastapi.testclient import TestClient

import app.db as db_module
import app.settings as settings_module


def _reset_caches() -> None:
    settings_module.get_settings.cache_clear()
    db_module.get_engine.cache_clear()


@pytest.fixture
def make_client(monkeypatch):
    """Build a TestClient for a fresh app after setting environment variables.

    Usage: `client = make_client(AGENT_ENABLED="true")`.
    """

    def _make(**env: str) -> TestClient:
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        _reset_caches()
        from app.main import create_app

        return TestClient(create_app())

    yield _make
    _reset_caches()
