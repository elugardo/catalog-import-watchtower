"""A retry against the startup sweep (#10; `_docs/architecture.md` -> *Import processing*, step 5).

The sweep runs in `app`; attempt 2 runs in `oncall-agent` or the CLI. Every
test here runs the sweep, which fails every `PROCESSING` import of the
database it is pointed at, so each one runs on its own database (`isolated_db`).

Who wins is decided by the import row: the sweep and attempt 2's upsert
transaction both lock it first. If the sweep gets there first, attempt 2 finds
its import ended and writes nothing. If attempt 2 is already in its upsert
transaction, the sweep waits for its commit and then finds nothing to sweep.
"""

import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import create_app
from app.services import alerts, importer
from app.services.agent_tools import retry_failed_import
from tests.integration.conftest import Namespace
from tests.integration.importing import alert_rows, all_products, import_row, products_by_sku
from tests.integration.test_alert_sweep import insert_attempt
from tests.integration.test_import_sweep import insert_import
from tests.integration.tooling import (
    attempt_rows,
    backend_pid_waiting_on_lock,
    claim,
    injected,
    paused,
)


def assert_one_consistent_end_state(engine, body: dict, products_before: list, result: dict) -> str:
    """Exactly one of the two consistent outcomes, never a mix; returns which one."""
    row = import_row(engine, body["id"])
    first, second = attempt_rows(engine, body["id"])
    vendor_products = products_by_sku(engine, body["vendor"]["id"])
    if row["status"] == "COMPLETED":
        winner = "attempt 2"
        assert (second["status"], second["error_code"]) == ("SUCCEEDED", None)
        assert row["product_count"] == 3 and row["completed_at"] is not None
        assert len(vendor_products) == 3
    else:
        winner = "sweep"
        assert (row["status"], row["failure_code"]) == ("FAILED", "INTERNAL_ERROR")
        assert (row["completed_at"], row["product_count"]) == (None, None)
        assert (second["status"], second["error_code"]) == ("FAILED", "INTERNAL_ERROR")
        assert second["finished_at"] is not None
        assert all_products(engine) == products_before  # nothing written under a FAILED import
    assert (first["status"], first["error_code"]) == ("FAILED", "TRANSIENT_STORAGE_TIMEOUT")
    assert "RUNNING" not in {first["status"], second["status"]}
    assert len(alert_rows(engine, body["id"])) == 1
    # The tool did not raise, and it reports the state that resulted.
    assert result["outcome"] == "DONE"
    assert (result["import_status"], result["failure_code"]) == (row["status"], row["failure_code"])
    assert [a["status"] for a in result["attempts"]] == [first["status"], second["status"]]

    again = retry_failed_import(body["id"])
    assert again["outcome"] == "REFUSED"
    assert len(attempt_rows(engine, body["id"])) == 2
    return winner


@pytest.fixture
def isolated_client(isolated_db, make_client):
    database_url, engine = isolated_db
    return make_client(DATABASE_URL=database_url), engine, Namespace(engine)


def test_the_sweep_wins_against_attempt_2_before_its_upsert(isolated_client, monkeypatch):
    client, engine, ns = isolated_client
    body = injected(client, ns.name())
    assert claim(body["alert"]["id"])
    [alert_before] = alert_rows(engine, body["id"])
    products_before = all_products(engine)
    outcome: list[dict] = []

    with paused(monkeypatch, importer, "validate_csv") as pause:
        worker = threading.Thread(target=lambda: outcome.append(retry_failed_import(body["id"])))
        worker.start()
        pause.wait()  # attempt 2 committed PROCESSING / RUNNING and is about to process

        assert importer.sweep_stuck_imports() == 1  # the app restarts meanwhile

        pause.release()
        worker.join(30)

    assert assert_one_consistent_end_state(engine, body, products_before, outcome[0]) == "sweep"
    [alert] = alert_rows(engine, body["id"])
    assert alert["reason"] == alerts.SWEEP_REASON
    assert (alert["status"], alert["claimed_at"]) == (
        alert_before["status"],
        alert_before["claimed_at"],
    )


def test_attempt_2_wins_against_the_sweep_inside_its_upsert(isolated_client, monkeypatch):
    client, engine, ns = isolated_client
    body = injected(client, ns.name())
    [alert_before] = alert_rows(engine, body["id"])
    products_before = all_products(engine)
    outcome: list[dict] = []
    swept: list[int] = []

    # Pause inside the upsert transaction, after its product statement.
    with paused(monkeypatch, importer, "_upsert_products", after=True) as pause:
        worker = threading.Thread(target=lambda: outcome.append(retry_failed_import(body["id"])))
        worker.start()
        pause.wait()

        sweeper = threading.Thread(target=lambda: swept.append(importer.sweep_stuck_imports()))
        sweeper.start()
        deadline = time.monotonic() + 10
        while not backend_pid_waiting_on_lock(engine):
            assert time.monotonic() < deadline, "the sweep never waited on the import row"
            time.sleep(0.05)

        pause.release()
        worker.join(30)
        sweeper.join(30)

    assert swept == [0]
    assert assert_one_consistent_end_state(engine, body, products_before, outcome[0]) == (
        "attempt 2"
    )
    # A success never touches the alert, and the sweep wrote none.
    assert alert_rows(engine, body["id"]) == [alert_before]


def test_a_sweep_during_the_retrys_locked_transaction_leaves_it_alone(isolated_client, monkeypatch):
    """The sweep runs while the guard's transaction is open: it sees `FAILED` and sweeps nothing."""
    client, engine, ns = isolated_client
    body = injected(client, ns.name())
    products_before = all_products(engine)
    outcome: list[dict] = []

    # Pause after attempt 2 was inserted, before the locked transaction commits.
    with paused(monkeypatch, importer, "begin_attempt", after=True) as pause:
        worker = threading.Thread(target=lambda: outcome.append(retry_failed_import(body["id"])))
        worker.start()
        pause.wait()

        assert importer.sweep_stuck_imports() == 0

        pause.release()
        worker.join(30)

    assert assert_one_consistent_end_state(engine, body, products_before, outcome[0]) == (
        "attempt 2"
    )


def test_a_crash_during_attempt_2_is_swept(isolated_client):
    client, engine, ns = isolated_client
    vendor_id = injected(client, ns.name())["vendor"]["id"]
    with engine.begin() as connection:
        import_id = insert_import(connection, vendor_id, "PROCESSING", "TRANSIENT_STORAGE_TIMEOUT")
        insert_attempt(connection, import_id, 1, "FAILED", "TRANSIENT_STORAGE_TIMEOUT")
        insert_attempt(connection, import_id, 2, "RUNNING")
        connection.execute(
            text(
                "INSERT INTO alerts (import_id, status, reason, claimed_at, created_at, updated_at)"
                " VALUES (:i, 'IN_PROGRESS', :r, now() - interval '1 minute',"
                " now() - interval '2 minutes', now() - interval '2 minutes')"
            ),
            {"i": import_id, "r": alerts.injected_reason(1)},
        )
    [alert_before] = alert_rows(engine, import_id)

    with TestClient(create_app()) as started:  # the lifespan runs the sweep
        detail = started.get(f"/api/imports/{import_id}").json()

    second = attempt_rows(engine, import_id)[1]
    assert (second["status"], second["error_code"]) == ("FAILED", "INTERNAL_ERROR")
    assert second["finished_at"] is not None
    row = import_row(engine, import_id)
    assert (row["status"], row["failure_code"]) == ("FAILED", "INTERNAL_ERROR")
    assert (row["completed_at"], row["product_count"]) == (None, None)
    [alert] = alert_rows(engine, import_id)
    assert (alert["id"], alert["reason"]) == (alert_before["id"], alerts.SWEEP_REASON)
    assert (alert["status"], alert["claimed_at"]) == ("IN_PROGRESS", alert_before["claimed_at"])
    assert "RUNNING" not in {a["status"] for a in detail["attempts"]}

    again = retry_failed_import(import_id)
    assert (again["outcome"], again["refused_reason"]) == ("REFUSED", "not_transient")
    assert len(attempt_rows(engine, import_id)) == 2
