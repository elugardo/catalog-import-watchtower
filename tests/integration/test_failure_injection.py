"""The synthetic failure injector and the failure-code mapping (#7; spec section 4 F4).

The injector is a check of the persisted `inject_transient_failure` on attempt 1,
after validation, at the start of the upsert transaction and before any product
statement. A real `OperationalError` there maps to the same code; anything else
stays `INTERNAL_ERROR`. "Products snapshot" is every product of every vendor.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db import get_engine
from app.main import create_app
from app.schemas.upload import UploadRequest
from app.services import importer
from tests.integration.contract import walk
from tests.integration.importing import (
    alert_rows,
    all_products,
    fixture_bytes,
    import_row,
    post_import,
    products_by_sku,
)

VALID = fixture_bytes("valid.csv")
UPDATE = fixture_bytes("update.csv")
INVALID = fixture_bytes("invalid.csv")
INJECTED_REASON = "TRANSIENT_STORAGE_TIMEOUT on attempt 1 (synthetic demo fault)"


def upload(client, name, data, filename="valid.csv", **kwargs) -> dict:
    response = post_import(client, name, data, filename=filename, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def assert_injected_failure(body: dict) -> None:
    assert (body["status"], body["failure_code"]) == ("FAILED", "TRANSIENT_STORAGE_TIMEOUT")
    assert body["inject_transient_failure"] is True
    assert (body["attempt_count"], body["recovered"]) == (1, False)
    assert (body["product_count"], body["completed_at"]) == (None, None)
    assert (body["validation_errors"], body["validation_error_count"]) == ([], 0)
    [attempt] = body["attempts"]
    assert (attempt["number"], attempt["status"], attempt["error_code"]) == (
        1,
        "FAILED",
        "TRANSIENT_STORAGE_TIMEOUT",
    )
    assert attempt["finished_at"] is not None
    assert (body["alert"]["status"], body["alert"]["reason"]) == ("OPEN", INJECTED_REASON)


@contextmanager
def product_statements() -> Iterator[list[str]]:
    """Every SQL statement the app's engine sends that names the products table."""
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        if "products" in statement:
            seen.append(statement)

    engine = get_engine()
    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


# ---- injection -----------------------------------------------------------------------


def test_injected_new_vendor_fails_and_writes_nothing(client, migrated_engine, ns):
    before = all_products(migrated_engine)
    vendor = ns.name("Injected New")

    with product_statements() as sent:
        body = upload(client, vendor, VALID, inject="true")

    assert_injected_failure(body)
    assert sent == []  # the fault is raised before any product statement
    assert body["row_count"] == 3
    assert all_products(migrated_engine) == before
    assert body["vendor"]["id"] in {v["id"] for v in walk(client, "/api/vendors")}

    products = client.get("/api/products", params={"vendor_id": body["vendor"]["id"]}).json()
    assert products == {"items": [], "total": 0}
    assert client.get(f"/api/imports/{body['id']}").json() == body


def test_injected_update_of_an_existing_vendor_changes_no_product(client, migrated_engine, ns):
    vendor = ns.name()
    vendor_id = upload(client, vendor, VALID)["vendor"]["id"]
    before = all_products(migrated_engine)

    body = upload(client, vendor, UPDATE, filename="update.csv", inject="true")

    assert (body["status"], body["failure_code"]) == ("FAILED", "TRANSIENT_STORAGE_TIMEOUT")
    assert all_products(migrated_engine) == before
    chair = products_by_sku(migrated_engine, vendor_id)["chair-001"]
    assert (chair["price_cents"], chair["quantity"]) == (14999, 8)

    # Without the flag the same file does write, so the check above could fail.
    with product_statements() as sent:
        plain = upload(client, vendor, UPDATE, filename="update.csv")
    assert plain["status"] == "COMPLETED"
    assert sent, "the observer sees the upsert when there is one"
    changed = products_by_sku(migrated_engine, vendor_id)["chair-001"]
    assert (changed["price_cents"], changed["quantity"]) == (12999, 20)
    assert changed["updated_at"] > chair["updated_at"]


@pytest.mark.parametrize(
    ("data", "filename", "reason"),
    [
        (INVALID, "invalid.csv", "VALIDATION_ERROR on attempt 1: 1 validation error"),
        (b"", "empty.csv", "VALIDATION_ERROR on attempt 1: 1 validation error"),
    ],
    ids=["invalid.csv", "empty"],
)
def test_validation_wins_over_injection(client, migrated_engine, ns, data, filename, reason):
    before = all_products(migrated_engine)

    body = upload(client, ns.name(), data, filename=filename, inject="true")

    assert (body["status"], body["failure_code"]) == ("FAILED", "VALIDATION_ERROR")
    assert body["attempts"][0]["error_code"] == "VALIDATION_ERROR"
    assert body["inject_transient_failure"] is True
    assert import_row(migrated_engine, body["id"])["inject_transient_failure"] is True
    assert body["alert"]["reason"] == reason
    assert all_products(migrated_engine) == before


def test_attempt_2_is_never_injected(client, migrated_engine, ns):
    injected = upload(client, ns.name("Retried"), VALID, inject="true")
    assert_injected_failure(injected)

    importer.run_attempt(injected["id"], 2)

    detail = client.get(f"/api/imports/{injected['id']}").json()
    assert (detail["status"], detail["failure_code"]) == ("COMPLETED", None)
    assert (detail["product_count"], detail["recovered"], detail["attempt_count"]) == (3, True, 2)
    assert detail["completed_at"] is not None
    assert [(a["number"], a["status"]) for a in detail["attempts"]] == [
        (1, "FAILED"),
        (2, "SUCCEEDED"),
    ]
    products = products_by_sku(migrated_engine, injected["vendor"]["id"])
    assert sorted(products) == ["chair-001", "lamp-003", "table-002"]


def test_the_flag_belongs_to_its_import_only(client, migrated_engine, ns):
    """An injected import in flight does not change another import's outcome."""
    in_flight = importer.create_import(
        UploadRequest(
            vendor_name=ns.name("In flight"),
            filename="valid.csv",
            data=VALID,
            inject_transient_failure=True,
        )
    )

    plain = upload(client, ns.name("Plain"), VALID)
    importer.run_attempt(in_flight, 1)

    assert (plain["status"], plain["attempt_count"]) == ("COMPLETED", 1)
    flagged = import_row(migrated_engine, in_flight)
    assert (flagged["status"], flagged["failure_code"]) == ("FAILED", "TRANSIENT_STORAGE_TIMEOUT")


# ---- the failure-code mapping ---------------------------------------------------------


def failing_after_the_first_statement(monkeypatch, exc: Exception) -> None:
    original = importer._upsert_products

    def failing_upsert(session, vendor_id, rows):
        original(session, vendor_id, rows)  # product statements are sent first
        raise exc

    monkeypatch.setattr(importer, "_upsert_products", failing_upsert)


@pytest.mark.parametrize(
    ("exc", "code", "reason"),
    [
        (
            OperationalError("UPDATE products", {}, Exception("server closed the connection")),
            "TRANSIENT_STORAGE_TIMEOUT",
            "TRANSIENT_STORAGE_TIMEOUT on attempt 1 (database OperationalError)",
        ),
        (
            IntegrityError("INSERT products", {}, Exception("duplicate key")),
            "INTERNAL_ERROR",
            "INTERNAL_ERROR on attempt 1 (unexpected error)",
        ),
        (
            RuntimeError("anything else"),
            "INTERNAL_ERROR",
            "INTERNAL_ERROR on attempt 1 (unexpected error)",
        ),
    ],
)
def test_exceptions_in_the_upsert_map_to_their_code_and_roll_back(
    client, migrated_engine, monkeypatch, ns, exc, code, reason
):
    vendor = ns.name()
    upload(client, vendor, VALID)
    before = all_products(migrated_engine)
    failing_after_the_first_statement(monkeypatch, exc)

    body = upload(client, vendor, UPDATE, filename="update.csv")

    assert (body["status"], body["failure_code"]) == ("FAILED", code)
    assert body["attempts"][0]["error_code"] == code
    assert body["alert"]["reason"] == reason
    assert all_products(migrated_engine) == before


def test_when_the_failure_write_fails_too_the_sweep_finishes_it(
    database_url, migrated_engine, monkeypatch, make_client, ns
):
    make_client(DATABASE_URL=database_url)  # points the app at the test database
    before = all_products(migrated_engine)

    def failing_upsert(session, vendor_id, rows):
        raise RuntimeError("first failure")

    def failing_finish(*args, **kwargs):
        raise OperationalError("UPDATE imports", {}, Exception("driver text CANARYDRIVER7"))

    monkeypatch.setattr(importer, "_upsert_products", failing_upsert)
    monkeypatch.setattr(importer, "_finish", failing_finish)
    client = TestClient(create_app(), raise_server_exceptions=False)
    response = post_import(client, ns.name(), VALID)

    assert response.status_code == 500
    assert response.json() == {"code": "INTERNAL_ERROR", "message": "internal error", "details": []}
    assert "CANARY" not in response.text
    with migrated_engine.connect() as connection:
        (import_id,) = connection.execute(
            text(
                "SELECT i.id FROM imports i JOIN vendors v ON v.id = i.vendor_id"
                " WHERE v.normalized_name LIKE :p"
            ),
            {"p": f"%{ns.token}%"},
        ).one()
    assert import_row(migrated_engine, import_id)["status"] == "PROCESSING"
    assert alert_rows(migrated_engine, import_id) == []
    assert all_products(migrated_engine) == before

    monkeypatch.undo()
    make_client(DATABASE_URL=database_url)
    with TestClient(create_app()):  # the lifespan runs the sweep
        pass

    swept = import_row(migrated_engine, import_id)
    assert (swept["status"], swept["failure_code"]) == ("FAILED", "INTERNAL_ERROR")
    [alert] = alert_rows(migrated_engine, import_id)
    assert (alert["status"], alert["reason"]) == (
        "OPEN",
        "INTERNAL_ERROR (found PROCESSING at startup)",
    )
