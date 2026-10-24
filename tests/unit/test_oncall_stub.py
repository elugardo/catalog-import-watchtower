"""The worker stub: logs why it is idle, makes no database connection, stops on a signal."""

import logging
import signal
import threading

import pytest

import app.oncall.__main__ as worker


@pytest.fixture
def stub_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nobody:nothing@127.0.0.1:1/nothing")
    from app.settings import get_settings

    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


def _run_until_stopped(monkeypatch) -> int:
    """Run main(); the fake signal.signal fires the SIGTERM handler right away."""
    handlers: dict[int, object] = {}

    def fake_signal(signum, handler):
        handlers[signum] = handler
        if signum == signal.SIGTERM:
            # Deliver the signal from another thread shortly after the loop starts.
            threading.Timer(0.05, handler, args=(signum, None)).start()

    monkeypatch.setattr(worker.signal, "signal", fake_signal)
    return worker.main([])


def test_idle_when_agent_disabled(stub_env, caplog):
    stub_env.delenv("AGENT_ENABLED", raising=False)
    caplog.set_level(logging.INFO, logger="app.oncall")

    exit_code = _run_until_stopped(stub_env)

    assert exit_code == 0
    idle_lines = [r.message for r in caplog.records if "idle" in r.message]
    assert len(idle_lines) == 1
    assert "AGENT_ENABLED is not true" in idle_lines[0]


def test_idle_with_not_implemented_notice_when_agent_enabled(stub_env, caplog):
    stub_env.setenv("AGENT_ENABLED", "true")
    caplog.set_level(logging.INFO, logger="app.oncall")

    exit_code = _run_until_stopped(stub_env)

    assert exit_code == 0
    idle_lines = [r.message for r in caplog.records if "idle" in r.message]
    assert len(idle_lines) == 1
    assert "not implemented yet" in idle_lines[0]
    assert "CIW-08.2" in idle_lines[0]


def test_stub_never_touches_the_database(stub_env, monkeypatch):
    import app.db as db_module

    def boom():
        raise AssertionError("the worker stub must not open a database connection")

    monkeypatch.setattr(db_module, "get_engine", boom)

    assert _run_until_stopped(stub_env) == 0
