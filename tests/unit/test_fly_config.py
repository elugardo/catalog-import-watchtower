"""`fly.toml` (CIW-10.1): the dev Fly config keeps the settings the issue
fixes, so a later edit cannot quietly turn on the agent, telemetry export, a
Fly-side build, an always-on machine, or point at another app."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FLY_TOML = ROOT / "fly.toml"
TEXT = FLY_TOML.read_text(encoding="utf-8")
CONFIG = tomllib.loads(TEXT)


def test_targets_only_ciw_dev_in_ewr():
    assert CONFIG["app"] == "ciw-dev"
    assert CONFIG["primary_region"] == "ewr"
    # No other Fly app name anywhere in the file (production arrives with #15).
    assert set(re.findall(r"\bciw-[a-z]+\b", TEXT)) == {"ciw-dev"}


def test_never_builds_on_fly():
    assert "build" not in CONFIG


def test_release_command_runs_the_migrations():
    assert CONFIG["deploy"]["release_command"] == "alembic upgrade head"


def test_env_disables_agent_and_telemetry_and_holds_no_secret():
    env = CONFIG["env"]
    assert env["AGENT_ENABLED"] == "false"
    assert env["OTEL_SDK_DISABLED"] == "true"
    for key in env:
        assert not re.search(r"DATABASE_URL|TOKEN|KEY|SECRET|PASSWORD", key), key
    assert not re.search(r"postgres(ql)?(\+\w+)?://", TEXT)


def test_app_and_worker_process_groups():
    processes = CONFIG["processes"]
    assert "uvicorn app.main:app" in processes["app"]
    assert "--port 8000" in processes["app"]
    # The worker never migrates: it runs only the on-call loop.
    assert processes["worker"] == "python -m app.oncall"


def test_http_service_stops_when_idle_and_serves_only_the_app_group():
    http = CONFIG["http_service"]
    assert http["processes"] == ["app"]
    assert http["internal_port"] == 8000
    assert http["auto_stop_machines"] == "stop"
    assert http["auto_start_machines"] is True
    assert http["min_machines_running"] == 0
    assert [check["path"] for check in http["checks"]] == ["/api/health"]


@pytest.mark.parametrize("key", ["services", "mounts", "statics"])
def test_no_extra_services_or_volumes(key):
    assert key not in CONFIG
