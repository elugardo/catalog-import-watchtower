"""PostgreSQL enforces the constraints of spec section 6 on the migrated schema.

Rows go in through the models (or plain SQL) inside the rolled-back `db`
session; each rejected write runs in its own savepoint so the test can go on.
"""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import AgentAction, Alert, Import, ImportAttempt, Product, Vendor
from app.models.enums import (
    AGENT_ACTIONS,
    ALERT_STATUSES,
    ATTEMPT_STATUSES,
    FAILURE_CODES,
    IMPORT_STATUSES,
)

MISSING_ID = 9_000_000_000_000  # no row has this id (and it is beyond 32 bits)


def add(db: Session, *rows):
    db.add_all(rows)
    db.flush()
    return rows[0] if len(rows) == 1 else rows


def assert_rejected(db: Session, statement_or_row) -> None:
    """The write raises IntegrityError; the savepoint keeps the session usable."""
    with pytest.raises(IntegrityError), db.begin_nested():
        if isinstance(statement_or_row, str):
            db.execute(text(statement_or_row))
        else:
            db.add(statement_or_row)
            db.flush()


def accepted(db: Session, statement_or_row) -> None:
    with db.begin_nested():
        if isinstance(statement_or_row, str):
            db.execute(text(statement_or_row))
        else:
            db.add(statement_or_row)
            db.flush()


def new_vendor(display_name: str = "Sample Furnishings") -> Vendor:
    return Vendor(display_name=display_name, normalized_name=display_name.strip().casefold())


def new_import(vendor: Vendor, **overrides) -> Import:
    values = {
        "vendor_id": vendor.id,
        "filename": "valid.csv",
        "csv_bytes": b"sku,name,price,quantity\n",
        "sha256": "0" * 64,
        "status": "PROCESSING",
    }
    return Import(**{**values, **overrides})


def new_product(vendor: Vendor, sku: str = "CHAIR-001") -> Product:
    return Product(
        vendor_id=vendor.id,
        sku=sku,
        normalized_sku=sku.casefold(),
        name="Oak Dining Chair",
        price_cents=14999,
        quantity=8,
    )


@pytest.fixture
def vendor(db) -> Vendor:
    return add(db, new_vendor())


@pytest.fixture
def one_of_each(db, vendor) -> dict[str, int]:
    """One row in every table, linked: the targets of the CHECK tests."""
    imp = add(db, new_import(vendor))
    attempt = add(db, ImportAttempt(import_id=imp.id, attempt_number=1, status="RUNNING"))
    alert = add(db, Alert(import_id=imp.id, status="OPEN", reason="import failed"))
    action = add(db, AgentAction(alert_id=alert.id, action="RUN_STARTED"))
    return {
        "imports": imp.id,
        "import_attempts": attempt.id,
        "alerts": alert.id,
        "agent_actions": action.id,
    }


# ---- unique constraints -------------------------------------------------------------


def test_vendor_normalized_name_is_unique(db, vendor):
    duplicate = Vendor(display_name="SAMPLE FURNISHINGS", normalized_name="sample furnishings")
    assert_rejected(db, duplicate)

    accepted(db, new_vendor("Other Furnishings"))


def test_product_sku_is_unique_per_vendor_not_globally(db, vendor):
    add(db, new_product(vendor, "CHAIR-001"))
    assert_rejected(db, new_product(vendor, "chair-001"))

    other_vendor = add(db, new_vendor("Second Vendor"))
    accepted(db, new_product(other_vendor, "CHAIR-001"))


def test_attempt_number_is_unique_per_import_not_globally(db, vendor):
    first, second = add(db, new_import(vendor), new_import(vendor))
    add(db, ImportAttempt(import_id=first.id, attempt_number=1, status="RUNNING"))

    assert_rejected(db, ImportAttempt(import_id=first.id, attempt_number=1, status="FAILED"))
    accepted(db, ImportAttempt(import_id=second.id, attempt_number=1, status="RUNNING"))
    accepted(db, ImportAttempt(import_id=first.id, attempt_number=2, status="RUNNING"))


def test_one_alert_per_import(db, vendor):
    first, second = add(db, new_import(vendor), new_import(vendor))
    add(db, Alert(import_id=first.id, status="OPEN", reason="import failed"))

    assert_rejected(db, Alert(import_id=first.id, status="OPEN", reason="again"))
    accepted(db, Alert(import_id=second.id, status="OPEN", reason="import failed"))


# ---- CHECK constraints --------------------------------------------------------------

CHECKS = [
    # (table, column, allowed values, nullable, rejected values)
    ("imports", "status", IMPORT_STATUSES, False, ["RECOVERED", "completed", "UNKNOWN"]),
    ("imports", "failure_code", FAILURE_CODES, True, ["validation_error", "TIMEOUT", ""]),
    ("import_attempts", "status", ATTEMPT_STATUSES, False, ["succeeded", "COMPLETED", "PENDING"]),
    ("import_attempts", "error_code", FAILURE_CODES, True, ["internal_error", "OTHER"]),
    ("alerts", "status", ALERT_STATUSES, False, ["open", "CLOSED", "ACKNOWLEDGED"]),
    ("agent_actions", "action", AGENT_ACTIONS, False, ["tool_call", "RETRY", "DISMISS"]),
]


@pytest.mark.parametrize(
    ("table", "column", "allowed", "nullable", "rejected"),
    CHECKS,
    ids=[f"{table}.{column}" for table, column, *_ in CHECKS],
)
def test_check_constraint_accepts_exactly_the_spec_values(
    db, one_of_each, table, column, allowed, nullable, rejected
):
    row_id = one_of_each[table]
    update = f"UPDATE {table} SET {column} = {{}} WHERE id = {row_id}"

    for value in rejected:
        assert_rejected(db, update.format(f"'{value}'"))
    for value in allowed:
        accepted(db, update.format(f"'{value}'"))
    if nullable:
        accepted(db, update.format("NULL"))
    else:
        assert_rejected(db, update.format("NULL"))  # NOT NULL, not the CHECK

    stored = db.execute(text(f"SELECT {column} FROM {table} WHERE id = {row_id}")).scalar_one()
    assert stored == (None if nullable else allowed[-1])


# ---- foreign keys -------------------------------------------------------------------


def test_children_must_point_at_an_existing_parent(db, vendor, one_of_each):
    ghost_vendor = Vendor(id=MISSING_ID, display_name="ghost", normalized_name="ghost")

    assert_rejected(db, new_product(ghost_vendor))
    assert_rejected(db, new_import(ghost_vendor))
    assert_rejected(db, ImportAttempt(import_id=MISSING_ID, attempt_number=1, status="RUNNING"))
    assert_rejected(db, Alert(import_id=MISSING_ID, status="OPEN", reason="import failed"))
    assert_rejected(db, AgentAction(alert_id=MISSING_ID, action="RUN_STARTED"))

    # The same rows with real parents go in.
    accepted(db, new_product(vendor))
    accepted(db, new_import(vendor))
    imp = one_of_each["imports"]
    accepted(db, ImportAttempt(import_id=imp, attempt_number=2, status="RUNNING"))
    second = add(db, new_import(vendor))
    accepted(db, Alert(import_id=second.id, status="OPEN", reason="import failed"))
    accepted(db, AgentAction(alert_id=one_of_each["alerts"], action="TOOL_CALL"))


# ---- values survive storage ---------------------------------------------------------


def test_largest_price_and_quantity_read_back_as_exact_ints(db, vendor):
    product = new_product(vendor)
    product.price_cents = 999_999_999_999  # 9 999 999 999.99, above the 32-bit range
    product.quantity = 999_999_999
    add(db, product)
    db.expire_all()

    price, quantity = db.execute(
        select(Product.price_cents, Product.quantity).where(Product.id == product.id)
    ).one()
    assert type(price) is int and price == 999_999_999_999
    assert type(quantity) is int and quantity == 999_999_999


def test_csv_bytes_read_back_byte_identical(db, vendor):
    raw = "﻿sku,name,price,quantity\r\nCAFE-1,Café crème,3.50,2\r\n".encode()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw and b"\xc3\xa9" in raw
    imp = add(db, new_import(vendor, csv_bytes=raw))
    db.expire_all()

    stored = db.execute(select(Import.csv_bytes).where(Import.id == imp.id)).scalar_one()
    assert type(stored) is bytes
    assert stored == raw


def test_offset_timestamp_reads_back_as_the_same_aware_instant(db, vendor):
    written = datetime(2026, 10, 24, 14, 30, 15, 123456, tzinfo=timezone(timedelta(hours=2)))
    imp = add(db, new_import(vendor))
    alert = add(db, Alert(import_id=imp.id, status="IN_PROGRESS", reason="x", claimed_at=written))
    db.expire_all()

    stored = db.execute(select(Alert.claimed_at).where(Alert.id == alert.id)).scalar_one()
    assert stored.tzinfo is not None
    assert stored == written
    assert stored.astimezone(UTC) == datetime(2026, 10, 24, 12, 30, 15, 123456, tzinfo=UTC)


def test_server_defaults_fill_the_not_null_columns(db, vendor):
    imp = add(db, new_import(vendor))
    db.expire_all()

    row = db.execute(
        text(
            "SELECT row_count, validation_errors_json, validation_error_count,"
            " inject_transient_failure, product_count, failure_code, completed_at, created_at"
            " FROM imports WHERE id = :id"
        ),
        {"id": imp.id},
    ).one()
    assert row[:7] == (0, [], 0, False, None, None, None)
    assert row.created_at.tzinfo is not None
