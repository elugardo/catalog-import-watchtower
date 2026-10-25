"""A third attempt is impossible, whatever the caller does (#10; spec section 9 scenario 5).

Every route to a third attempt through the six tools and the CLI: repeated
calls after a `DONE` retry, calls after a failed attempt 2, calls after the
sweep failed attempt 2, and concurrent calls. No tool and no CLI sub-command
takes an attempt number.
"""

import inspect

from fastapi.testclient import TestClient

from app.main import create_app
from app.oncall import cli as cli_module
from app.services import agent_tools
from app.services.agent_tools import retry_failed_import
from tests.integration.conftest import Namespace
from tests.integration.test_oncall_cli import cli
from tests.integration.tooling import (
    attempt_rows,
    force_upsert_error,
    hold_lock_until_contended,
    injected,
    operational_error,
    run_concurrently,
)


def every_route(import_id: int, database_url: str) -> list[dict]:
    """Every tool and CLI call that could be asked for another attempt."""
    results = [retry_failed_import(import_id) for _ in range(3)]
    for tool in agent_tools.TOOL_NAMES:
        if tool == "retry_failed_import":
            completed = cli(tool, str(import_id), database_url=database_url)
            assert completed.returncode == 1, completed.stderr
        elif tool in {"get_import_attempts", "get_import_diagnostics"}:
            assert cli(tool, str(import_id), database_url=database_url).returncode == 0
    return results


def assert_never_more_than_two(engine, import_id: int, results: list[dict]) -> None:
    assert all(r["outcome"] == "REFUSED" for r in results)
    assert len(attempt_rows(engine, import_id)) == 2


def test_after_a_done_retry(client, database_url, migrated_engine, ns):
    body = injected(client, ns.name())
    assert retry_failed_import(body["id"])["import_status"] == "COMPLETED"

    results = every_route(body["id"], database_url)

    assert_never_more_than_two(migrated_engine, body["id"], results)


def test_after_a_failed_attempt_2(client, database_url, migrated_engine, ns, monkeypatch):
    body = injected(client, ns.name())
    with monkeypatch.context() as patched:
        force_upsert_error(patched, operational_error())
        assert retry_failed_import(body["id"])["failure_code"] == "TRANSIENT_STORAGE_TIMEOUT"

    results = every_route(body["id"], database_url)

    assert_never_more_than_two(migrated_engine, body["id"], results)


def test_after_the_sweep_failed_attempt_2(isolated_db, make_client, monkeypatch):
    database_url, engine = isolated_db
    body = injected(make_client(DATABASE_URL=database_url), Namespace(engine).name())

    # A crash inside attempt 2: the attempt is left RUNNING, the import PROCESSING.
    from app.services import importer

    monkeypatch.setattr(importer, "process_attempt", lambda *args: None)
    retry_failed_import(body["id"])
    monkeypatch.undo()
    make_client(DATABASE_URL=database_url)
    assert [a["status"] for a in attempt_rows(engine, body["id"])] == ["FAILED", "RUNNING"]
    with TestClient(create_app()):  # the lifespan sweep fails attempt 2
        pass

    results = every_route(body["id"], database_url)

    assert_never_more_than_two(engine, body["id"], results)
    assert attempt_rows(engine, body["id"])[1]["error_code"] == "INTERNAL_ERROR"


def test_concurrent_calls(client, migrated_engine, ns, monkeypatch):
    body = injected(client, ns.name())
    hold_lock_until_contended(monkeypatch, migrated_engine, parties=4)

    results = run_concurrently(*(lambda: retry_failed_import(body["id"]) for _ in range(4)))

    assert sorted(r["outcome"] for r in results) == ["DONE"] + ["REFUSED"] * 3
    assert len(attempt_rows(migrated_engine, body["id"])) == 2


def test_no_tool_or_sub_command_takes_an_attempt_number(database_url):
    for name, tool in agent_tools.TOOLS.items():
        assert set(inspect.signature(tool).parameters) <= {"alert_id", "import_id", "reason"}, name
    assert set().union(*map(set, cli_module.ARGUMENTS.values())) == {
        "alert_id",
        "import_id",
        "reason",
    }
    # An extra argument (an attempt number) is a usage error.
    assert cli("retry_failed_import", "1", "3", database_url=database_url).returncode == 2
