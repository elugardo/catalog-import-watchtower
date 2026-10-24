"""`check_database` gives up at the health deadline even when the probe itself hangs (slow DNS)."""

import time

import app.db as db_module
from app.settings import get_settings


def test_check_database_returns_error_at_the_deadline_when_the_probe_hangs(monkeypatch):
    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "1")
    get_settings.cache_clear()
    db_module.get_engine.cache_clear()

    def hanging_probe() -> bool:
        time.sleep(10)
        return True

    monkeypatch.setattr(db_module, "_probe_database", hanging_probe)

    started = time.monotonic()
    result = db_module.check_database()
    elapsed = time.monotonic() - started

    get_settings.cache_clear()
    assert result is False
    assert 1.5 <= elapsed < 5, f"gave up after {elapsed:.1f}s; deadline is connect timeout + 1s"


def test_check_database_reports_ok_when_the_probe_succeeds(monkeypatch):
    monkeypatch.setattr(db_module, "_probe_database", lambda: True)

    assert db_module.check_database() is True
