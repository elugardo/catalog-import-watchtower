"""The startup sweep writes the alert (#7; `_docs/architecture.md` -> *Import processing*, step 5).

Rows are inserted directly to reproduce what a crash leaves behind.
"""

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import create_app
from tests.integration.conftest import Namespace
from tests.integration.contract import walk
from tests.integration.importing import alert_rows, fixture_bytes, import_row, post_import
from tests.integration.test_import_sweep import attempt_rows, insert_import

SWEEP_REASON = "INTERNAL_ERROR (found PROCESSING at startup)"


def insert_attempt(connection, import_id: int, number: int, status: str, error_code=None) -> None:
    connection.execute(
        text(
            "INSERT INTO import_attempts (import_id, attempt_number, status, error_code,"
            " finished_at) VALUES (:i, :n, :s, :e, CASE WHEN :done THEN now() END)"
        ),
        {"i": import_id, "n": number, "s": status, "e": error_code, "done": status != "RUNNING"},
    )


def start_app() -> list[dict]:
    """Run the lifespan (the sweep) and return every alert the API lists."""
    with TestClient(create_app()) as client:
        return list(walk(client, "/api/alerts"))


def test_the_sweep_alerts_every_stuck_import_once(make_client, isolated_db):
    # The sweep touches every PROCESSING import, so it runs on its own database.
    database_url, migrated_engine = isolated_db
    ns = Namespace(migrated_engine)
    seed = make_client(DATABASE_URL=database_url)
    vendor_id = post_import(seed, ns.name(), fixture_bytes("valid.csv")).json()["vendor"]["id"]
    with migrated_engine.begin() as connection:
        running = insert_import(connection, vendor_id, "PROCESSING")
        insert_attempt(connection, running, 1, "RUNNING")
        no_attempt = insert_import(connection, vendor_id, "PROCESSING")
        # The #28 case: attempt 1 failed transiently, the retry crashed mid-way.
        retried = insert_import(connection, vendor_id, "PROCESSING")
        insert_attempt(connection, retried, 1, "FAILED", "TRANSIENT_STORAGE_TIMEOUT")
        insert_attempt(connection, retried, 2, "RUNNING")
        connection.execute(
            text(
                "INSERT INTO alerts (import_id, status, reason, claimed_at, created_at, updated_at)"
                " VALUES (:i, 'IN_PROGRESS', 'TRANSIENT_STORAGE_TIMEOUT on attempt 1"
                " (synthetic demo fault)', now() - interval '1 minute',"
                " now() - interval '2 minutes', now() - interval '2 minutes')"
            ),
            {"i": retried},
        )
        # Left by a build before #7: FAILED with no alert. Never backfilled.
        legacy = insert_import(connection, vendor_id, "FAILED", "VALIDATION_ERROR")
    [claimed] = alert_rows(migrated_engine, retried)

    listed = start_app()

    for import_id in (running, no_attempt):
        row = import_row(migrated_engine, import_id)
        assert (row["status"], row["failure_code"]) == ("FAILED", "INTERNAL_ERROR")
        [alert] = alert_rows(migrated_engine, import_id)
        assert (alert["status"], alert["reason"], alert["claimed_at"]) == (
            "OPEN",
            SWEEP_REASON,
            None,
        )
        assert alert["created_at"] == alert["updated_at"]
        assert alert["id"] in {item["id"] for item in listed}
    assert attempt_rows(migrated_engine, no_attempt) == []
    assert [a["status"] for a in attempt_rows(migrated_engine, retried)] == ["FAILED", "FAILED"]

    [after] = alert_rows(migrated_engine, retried)
    assert after["id"] == claimed["id"]
    assert after["reason"] == SWEEP_REASON
    assert (after["status"], after["claimed_at"], after["created_at"]) == (
        "IN_PROGRESS",
        claimed["claimed_at"],
        claimed["created_at"],
    )
    assert after["updated_at"] > claimed["updated_at"]

    assert alert_rows(migrated_engine, legacy) == []

    # A second start changes no alert row, and requests do not backfill either.
    snapshot = {i: alert_rows(migrated_engine, i) for i in (running, no_attempt, retried, legacy)}
    with TestClient(create_app()) as client:
        client.get(f"/api/imports/{legacy}")
        client.get("/api/alerts")
    assert {i: alert_rows(migrated_engine, i) for i in snapshot} == snapshot
