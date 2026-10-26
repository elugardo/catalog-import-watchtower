"""`fly.prod.toml` (CIW-10.2): the production Fly config is the dev config
with only the app name changed, so prod cannot quietly turn on the agent,
telemetry export, a Fly-side build or an always-on machine, or point at the
dev app."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
TEXT = (ROOT / "fly.prod.toml").read_text(encoding="utf-8")
CONFIG = tomllib.loads(TEXT)
DEV = tomllib.loads((ROOT / "fly.toml").read_text(encoding="utf-8"))


def test_targets_only_ciw_prod_in_ewr():
    assert CONFIG["app"] == "ciw-prod"
    assert CONFIG["primary_region"] == "ewr"
    # No other Fly app name anywhere in the file, the dev app included.
    assert set(re.findall(r"\bciw-[a-z]+\b", TEXT)) == {"ciw-prod"}


def test_mirrors_the_dev_config_except_the_app_name():
    assert {k: v for k, v in CONFIG.items() if k != "app"} == {
        k: v for k, v in DEV.items() if k != "app"
    }


def test_never_builds_on_fly():
    assert "build" not in CONFIG


def test_release_command_runs_the_migrations_with_a_rolling_strategy():
    assert CONFIG["deploy"]["release_command"] == "alembic upgrade head"
    assert CONFIG["deploy"]["strategy"] == "rolling"


def test_env_disables_agent_and_telemetry_and_holds_no_secret():
    env = CONFIG["env"]
    assert env["AGENT_ENABLED"] == "false"
    assert env["OTEL_SDK_DISABLED"] == "true"
    for key in env:
        assert not re.search(r"DATABASE_URL|TOKEN|KEY|SECRET|PASSWORD", key), key
    assert not re.search(r"postgres(ql)?(\+\w+)?://", TEXT)


def test_worker_group_exists_but_only_the_app_group_serves_http():
    assert CONFIG["processes"]["worker"] == "python -m app.oncall"
    assert "uvicorn app.main:app" in CONFIG["processes"]["app"]
    assert CONFIG["http_service"]["processes"] == ["app"]


def test_http_service_stops_when_idle_and_checks_health():
    http = CONFIG["http_service"]
    assert http["internal_port"] == 8000
    assert http["auto_stop_machines"] == "stop"
    assert http["auto_start_machines"] is True
    assert http["min_machines_running"] == 0
    assert [check["path"] for check in http["checks"]] == ["/api/health"]


@pytest.mark.parametrize("key", ["services", "mounts", "statics"])
def test_no_extra_services_or_volumes(key):
    assert key not in CONFIG
