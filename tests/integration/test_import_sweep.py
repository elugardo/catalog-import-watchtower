"""The startup sweep (`_docs/architecture.md` -> *Import processing*, step 5)."""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import create_app
from tests.integration.conftest import Namespace
from tests.integration.importing import fixture_bytes, import_row, post_import


def insert_import(connection, vendor_id: int, status: str, failure_code=None) -> int:
    return connection.execute(
        text(
            "INSERT INTO imports (vendor_id, filename, csv_bytes, sha256, status, failure_code,"
            " product_count, completed_at) VALUES (:v, 'x.csv', '\\x00', :sha, :s, :f,"
            " :pc, CASE WHEN :done THEN now() END) RETURNING id"
        ),
        {
            "v": vendor_id,
            "sha": "0" * 64,
            "s": status,
            "f": failure_code,
            "pc": 3 if status == "COMPLETED" else None,
            "done": status == "COMPLETED",
        },
    ).scalar_one()


def insert_attempt(connection, import_id: int, status: str, error_code=None) -> None:
    connection.execute(
        text(
            "INSERT INTO import_attempts (import_id, attempt_number, status, error_code,"
            " finished_at) VALUES (:i, 1, :s, :e, CASE WHEN :done THEN now() END)"
        ),
        {"i": import_id, "s": status, "e": error_code, "done": status != "RUNNING"},
    )


def attempt_rows(engine, import_id: int) -> list[dict]:
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text("SELECT * FROM import_attempts WHERE import_id = :i ORDER BY attempt_number"),
                {"i": import_id},
            ).mappings()
        ]


def test_startup_sweep_fails_stuck_imports_and_their_running_attempt(make_client, isolated_db):
    # The sweep touches every PROCESSING import, so it runs on its own database.
    database_url, migrated_engine = isolated_db
    ns = Namespace(migrated_engine)
    seed = make_client(DATABASE_URL=database_url)
    vendor_id = post_import(seed, ns.name(), fixture_bytes("valid.csv")).json()["vendor"]["id"]
    with migrated_engine.begin() as connection:
        stuck = insert_import(connection, vendor_id, "PROCESSING")
        insert_attempt(connection, stuck, "RUNNING")
        completed = insert_import(connection, vendor_id, "COMPLETED")
        insert_attempt(connection, completed, "SUCCEEDED")
        failed = insert_import(connection, vendor_id, "FAILED", "VALIDATION_ERROR")
        insert_attempt(connection, failed, "FAILED", "VALIDATION_ERROR")
    untouched = {
        i: (import_row(migrated_engine, i), attempt_rows(migrated_engine, i))
        for i in (completed, failed)
    }

    with TestClient(create_app()) as client:  # the lifespan runs the sweep
        detail = client.get(f"/api/imports/{stuck}").json()

    swept = import_row(migrated_engine, stuck)
    assert (swept["status"], swept["failure_code"]) == ("FAILED", "INTERNAL_ERROR")
    assert swept["completed_at"] is None
    assert swept["product_count"] is None
    [attempt] = attempt_rows(migrated_engine, stuck)
    assert (attempt["status"], attempt["error_code"]) == ("FAILED", "INTERNAL_ERROR")
    assert attempt["finished_at"] is not None
    assert detail["status"] == "FAILED"
    assert detail["attempts"][0]["finished_at"] is not None
    for import_id, (row, attempts) in untouched.items():
        assert import_row(migrated_engine, import_id) == row
        assert attempt_rows(migrated_engine, import_id) == attempts


def test_the_worker_does_not_sweep():
    """The sweep belongs to `app`'s lifespan; `python -m app.oncall` never runs it."""
    oncall = Path(__file__).resolve().parents[2] / "app" / "oncall"
    for module in oncall.rglob("*.py"):
        assert "sweep_stuck_imports" not in module.read_text(encoding="utf-8"), module
