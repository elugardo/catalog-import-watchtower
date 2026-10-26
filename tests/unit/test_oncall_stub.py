"""The worker without credentials: one idle line naming the reason, no claim, no database.

`python -m app.oncall` never claims (and never connects) when `AGENT_ENABLED`
is not true, `LLM_PROVIDER` is not `anthropic`, `ANTHROPIC_API_KEY` is missing
or empty, or `LLM_MODEL` is empty. The idle line names which, never a value.
"""

import logging
import signal
import threading

import pytest

import app.oncall.__main__ as worker

CANARY = "CANARY-IDLE-5d1e"


@pytest.fixture
def stub_env(monkeypatch, reset_caches):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://nobody:nothing@127.0.0.1:1/nothing")
    monkeypatch.setenv("AGENT_ENABLED", "true")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", f"model-{CANARY}")
    monkeypatch.setenv("ANTHROPIC_API_KEY", f"key-{CANARY}")
    reset_caches()

    import app.db as db_module

    def boom():
        raise AssertionError("an idle worker must not open a database connection")

    monkeypatch.setattr(db_module, "get_engine", boom)
    return monkeypatch


def _run_until_stopped(monkeypatch) -> int:
    """Run main(); the fake signal.signal fires the SIGTERM handler right away."""

    def fake_signal(signum, handler):
        if signum == signal.SIGTERM:
            threading.Timer(0.05, handler, args=(signum, None)).start()

    monkeypatch.setattr(worker.signal, "signal", fake_signal)
    return worker.main([])


def _idle_line(caplog) -> str:
    lines = [r.getMessage() for r in caplog.records if "idle" in r.getMessage()]
    assert len(lines) == 1, lines
    return lines[0]


@pytest.mark.parametrize(
    ("variable", "value", "reason"),
    [
        ("AGENT_ENABLED", None, "AGENT_ENABLED is not true"),
        ("AGENT_ENABLED", "false", "AGENT_ENABLED is not true"),
        ("LLM_PROVIDER", f"other-{CANARY}", "LLM_PROVIDER is not anthropic"),
        ("LLM_PROVIDER", None, "LLM_PROVIDER is not anthropic"),
        ("ANTHROPIC_API_KEY", None, "ANTHROPIC_API_KEY is not set"),
        ("ANTHROPIC_API_KEY", "", "ANTHROPIC_API_KEY is not set"),
        ("ANTHROPIC_API_KEY", "   ", "ANTHROPIC_API_KEY is not set"),
        ("LLM_MODEL", "", "LLM_MODEL is not set"),
    ],
    ids=lambda v: repr(v)[:30],
)
def test_idle_line_names_the_reason_and_no_value(stub_env, caplog, variable, value, reason):
    if value is None:
        stub_env.delenv(variable, raising=False)
    else:
        stub_env.setenv(variable, value)
    caplog.set_level(logging.INFO, logger="app.oncall")

    assert _run_until_stopped(stub_env) == 0

    line = _idle_line(caplog)
    assert line == f"oncall-agent: idle because {reason}"
    assert CANARY not in caplog.text


def test_with_credentials_it_polls_instead_of_idling(stub_env, caplog, monkeypatch):
    from app.oncall import llm, poller

    polled = threading.Event()

    def fake_poll(client, config):
        polled.set()
        raise RuntimeError(CANARY)  # a failed poll logs the type only

    monkeypatch.setattr(poller, "poll_once", fake_poll)
    monkeypatch.setattr(llm, "make_client", lambda: object())
    caplog.set_level(logging.INFO, logger="app.oncall")

    assert _run_until_stopped(stub_env) == 0

    assert polled.is_set()
    assert not [r for r in caplog.records if "idle" in r.getMessage()]
    assert "poll failed: RuntimeError" in caplog.text
    assert "key-" + CANARY not in caplog.text
