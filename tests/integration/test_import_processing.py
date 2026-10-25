"""Processing and persistence of `POST /api/imports` (spec section 4 F2, section 6, section 9 1-3)."""

import hashlib
import logging

from sqlalchemy import create_engine, text

from app.services import importer
from tests.integration.importing import (
    HEADER,
    assert_failed_validation,
    csv_rows,
    fixture_bytes,
    import_row,
    post_import,
    products_by_sku,
    products_snapshot,
)

VALID = fixture_bytes("valid.csv")
UPDATE = fixture_bytes("update.csv")
INVALID = fixture_bytes("invalid.csv")


def upload(client, name, data, filename="valid.csv", **kwargs) -> dict:
    response = post_import(client, name, data, filename=filename, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def strictly_later(after, before) -> bool:
    return after > before


# ---- scenario 1 -----------------------------------------------------------------


def test_scenario_1_valid_import(client, migrated_engine, ns):
    body = upload(client, ns.name(), VALID)

    assert body["status"] == "COMPLETED"
    assert body["product_count"] == 3
    assert body["row_count"] == 3
    assert body["attempt_count"] == 1
    assert body["recovered"] is False
    assert body["failure_code"] is None
    assert body["validation_errors"] == []
    assert body["validation_error_count"] == 0
    assert body["completed_at"] is not None
    assert body["inject_transient_failure"] is False
    assert body["filename"] == "valid.csv"
    assert body["sha256"] == hashlib.sha256(VALID).hexdigest()
    assert len(body["attempts"]) == 1
    attempt = body["attempts"][0]
    assert attempt["number"] == 1
    assert attempt["status"] == "SUCCEEDED"
    assert attempt["error_code"] is None
    assert attempt["trace_id"] is None
    assert attempt["finished_at"] is not None
    assert body["alert"] is None
    assert body["agent_actions"] == []

    assert client.get(f"/api/imports/{body['id']}").json() == body
    assert bytes(import_row(migrated_engine, body["id"])["csv_bytes"]) == VALID

    products = products_by_sku(migrated_engine, body["vendor"]["id"])
    assert {sku: (p["sku"], p["price_cents"], p["quantity"]) for sku, p in products.items()} == {
        "chair-001": ("CHAIR-001", 14999, 8),
        "table-002": ("TABLE-002", 49900, 3),
        "lamp-003": ("LAMP-003", 3950, 12),
    }


# ---- scenario 2 and the upsert rules ------------------------------------------------


def test_scenario_2_upsert_not_replacement(client, migrated_engine, ns):
    vendor_id = upload(client, ns.name(), VALID)["vendor"]["id"]
    before = products_by_sku(migrated_engine, vendor_id)

    body = upload(client, ns.name(), UPDATE, filename="update.csv")

    assert body["status"] == "COMPLETED"
    assert body["product_count"] == 1
    after = products_by_sku(migrated_engine, vendor_id)
    assert len(after) == 3
    chair, old_chair = after["chair-001"], before["chair-001"]
    assert chair["id"] == old_chair["id"]
    assert (chair["price_cents"], chair["quantity"]) == (12999, 20)
    assert strictly_later(chair["updated_at"], old_chair["updated_at"])
    assert after["table-002"] == before["table-002"]
    assert after["lamp-003"] == before["lamp-003"]


def test_identical_reupload_still_updates_every_row(client, migrated_engine, ns):
    vendor_id = upload(client, ns.name(), VALID)["vendor"]["id"]
    before = products_by_sku(migrated_engine, vendor_id)

    upload(client, ns.name(), VALID)

    after = products_by_sku(migrated_engine, vendor_id)
    assert after.keys() == before.keys()
    for sku, row in after.items():
        old = before[sku]
        assert row["id"] == old["id"]
        assert {k: v for k, v in row.items() if k != "updated_at"} == {
            k: v for k, v in old.items() if k != "updated_at"
        }
        assert strictly_later(row["updated_at"], old["updated_at"]), sku


def test_sku_case_across_uploads_updates_the_same_row(client, migrated_engine, ns):
    vendor_id = upload(client, ns.name(), VALID)["vendor"]["id"]
    chair_id = products_by_sku(migrated_engine, vendor_id)["chair-001"]["id"]

    upload(client, ns.name(), HEADER + b"chair-001,Oak Dining Chair,149.99,8\n")

    after = products_by_sku(migrated_engine, vendor_id)
    assert len(after) == 3
    assert after["chair-001"]["id"] == chair_id
    assert after["chair-001"]["sku"] == "chair-001"


def test_same_sku_for_another_vendor_is_another_product(client, migrated_engine, ns):
    first = upload(client, ns.name("First"), VALID)["vendor"]["id"]
    before = products_snapshot(migrated_engine, first)

    second = upload(client, ns.name("Second"), VALID)["vendor"]["id"]

    assert second != first
    assert len(products_snapshot(migrated_engine, second)) == 3
    assert products_snapshot(migrated_engine, first) == before


# ---- scenario 3 and validation failures -----------------------------------------------


def test_scenario_3_invalid_file_changes_nothing(client, migrated_engine, ns):
    vendor_id = upload(client, ns.name(), VALID)["vendor"]["id"]
    before = products_snapshot(migrated_engine, vendor_id)

    body = upload(client, ns.name(), INVALID, filename="invalid.csv")

    assert_failed_validation(body)
    assert body["row_count"] == 4
    assert len(body["validation_errors"]) == 1
    error = body["validation_errors"][0]
    assert (error["line"], error["column"]) == (4, "quantity")
    assert error["message"]
    assert body["validation_error_count"] == 1
    assert body["alert"]["status"] == "OPEN"  # the alert itself: test_failure_alerts.py
    after = products_snapshot(migrated_engine, vendor_id)
    assert after == before
    skus = {row["normalized_sku"]: row for row in after}
    assert "stool-004" not in skus
    assert skus["chair-001"]["price_cents"] == 14999


def test_late_invalid_row_changes_no_product(client, migrated_engine, ns):
    # The first rows overlap the existing SKUs, so an early write would show.
    vendor_id = upload(client, ns.name(), HEADER + csv_rows(10))["vendor"]["id"]
    before = products_snapshot(migrated_engine, vendor_id)

    data = HEADER + csv_rows(400) + b"BAD-PRICE,Broken Item,12.345,1\n"
    body = upload(client, ns.name(), data)

    assert_failed_validation(body)
    assert body["validation_errors"][0]["line"] == 402
    assert products_snapshot(migrated_engine, vendor_id) == before


def test_empty_file(client, ns):
    body = upload(client, ns.name(), b"", filename="empty.csv")

    assert_failed_validation(body)
    assert body["row_count"] == 0
    assert [(e["line"], e["column"]) for e in body["validation_errors"]] == [(1, "file")]
    assert body["sha256"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_500_rows_pass(client, ns):
    body = upload(client, ns.name(), HEADER + csv_rows(500))
    assert body["status"] == "COMPLETED"
    assert body["product_count"] == 500


def test_501_rows_fail_with_one_file_error(client, migrated_engine, ns):
    body = upload(client, ns.name(), HEADER + csv_rows(501))

    assert_failed_validation(body)
    assert body["row_count"] == 501
    assert body["validation_errors"] == [
        {"line": 1, "column": "file", "message": "file has 501 data rows, limit 500"}
    ]
    assert products_snapshot(migrated_engine, body["vendor"]["id"]) == []


def test_unparseable_record_is_a_validation_failure(client, migrated_engine, ns):
    vendor_id = upload(client, ns.name(), VALID)["vendor"]["id"]
    before = products_snapshot(migrated_engine, vendor_id)
    data = HEADER + b'BIG-1,"' + b"n" * 131_073 + b'",1.00,1\n' + csv_rows(600)
    assert len(data) < 256 * 1024

    body = upload(client, ns.name(), data)

    assert_failed_validation(body)
    assert [(e["line"], e["column"]) for e in body["validation_errors"]] == [(2, "row")]
    assert body["validation_error_count"] == 1
    assert body["row_count"] == 1
    assert products_snapshot(migrated_engine, vendor_id) == before


def test_only_the_first_20_errors_are_stored(client, ns):
    data = HEADER + b"".join(f"Q-{n},Item {n},1.00,-1\n".encode() for n in range(25))

    body = upload(client, ns.name(), data)

    assert_failed_validation(body)
    assert body["validation_error_count"] == 25
    assert [e["line"] for e in body["validation_errors"]] == list(range(2, 22))
    assert {e["column"] for e in body["validation_errors"]} == {"quantity"}


def test_error_count_stops_at_the_validator_cap(client, ns):
    data = HEADER + b"bad sku!,,x,y\n" * 500

    body = upload(client, ns.name(), data)

    assert_failed_validation(body)
    assert len(body["validation_errors"]) == 20
    assert body["validation_error_count"] == 1000


# ---- durable steps and rollback ------------------------------------------------------


def test_processing_and_running_are_committed_before_the_upsert(
    client, database_url, monkeypatch, ns
):
    seen: dict = {}
    original = importer._upsert_products

    def observing_upsert(session, vendor_id, rows):
        observer = create_engine(database_url)
        try:
            with observer.connect() as connection:
                seen["import"] = connection.execute(
                    text(
                        "SELECT i.status, a.status AS attempt, a.attempt_number FROM imports i "
                        "JOIN import_attempts a ON a.import_id = i.id "
                        "WHERE i.vendor_id = :v ORDER BY i.id DESC LIMIT 1"
                    ),
                    {"v": vendor_id},
                ).one()
        finally:
            observer.dispose()
        return original(session, vendor_id, rows)

    monkeypatch.setattr(importer, "_upsert_products", observing_upsert)

    body = upload(client, ns.name(), VALID)

    assert body["status"] == "COMPLETED"
    assert tuple(seen["import"]) == ("PROCESSING", "RUNNING", 1)


class Boom(RuntimeError):
    pass


def test_runtime_failure_in_the_upsert_rolls_everything_back(
    client, migrated_engine, monkeypatch, ns
):
    vendor_id = upload(client, ns.name(), VALID)["vendor"]["id"]
    before = products_snapshot(migrated_engine, vendor_id)
    original = importer._upsert_products
    written: dict = {}

    def failing_upsert(session, vendor_id, rows):
        original(session, vendor_id, rows)
        # Inside the transaction, the rows are there before the failure.
        written["count"] = session.execute(
            text("SELECT count(*) FROM products WHERE vendor_id = :v AND normalized_sku = 'new-1'"),
            {"v": vendor_id},
        ).scalar_one()
        raise Boom("forced failure inside the upsert transaction")

    monkeypatch.setattr(importer, "_upsert_products", failing_upsert)

    body = upload(client, ns.name(), HEADER + b"NEW-1,New Item,1.00,1\nCHAIR-001,Chair,1.00,1\n")

    assert written["count"] == 1
    assert body["status"] == "FAILED"
    assert body["failure_code"] == "INTERNAL_ERROR"
    assert body["product_count"] is None
    assert body["completed_at"] is None
    assert body["attempts"][0]["status"] == "FAILED"
    assert body["attempts"][0]["error_code"] == "INTERNAL_ERROR"
    assert body["attempts"][0]["finished_at"] is not None
    assert products_snapshot(migrated_engine, vendor_id) == before
    assert client.get(f"/api/imports/{body['id']}").json() == body


def test_injection_flag_is_stored(client, migrated_engine, ns):
    body = upload(client, ns.name(), VALID, inject="true")

    assert body["inject_transient_failure"] is True
    assert import_row(migrated_engine, body["id"])["inject_transient_failure"] is True
    assert body["status"] == "FAILED"  # the injector itself: test_failure_injection.py
    assert body["attempt_count"] == 1


# ---- no catalog content in logs --------------------------------------------------------


def test_logs_carry_no_catalog_content(client, caplog, monkeypatch, ns):
    caplog.set_level(logging.DEBUG)
    vendor = ns.name()

    upload(client, vendor, VALID)
    upload(client, vendor, UPDATE, filename="update.csv")
    upload(client, vendor, INVALID, filename="invalid.csv")
    upload(client, vendor, VALID, inject="true")

    def failing_upsert(session, vendor_id, rows):
        raise Boom(f"failure quoting {rows[0]['sku']} {rows[0]['name']}")

    monkeypatch.setattr(importer, "_upsert_products", failing_upsert)
    assert upload(client, vendor, VALID)["failure_code"] == "INTERNAL_ERROR"

    assert caplog.records, "expected the importer to log something"
    forbidden = [
        vendor,
        vendor.casefold(),
        ns.token,
        "CHAIR-001",
        "TABLE-002",
        "LAMP-003",
        "STOOL-004",
        "Oak Dining Chair",
        "Round Dining Table",
        "Desk Lamp",
        "Bar Stool",
        "-2",
    ]
    for record in caplog.records:
        rendered = record.getMessage() + (record.exc_text or "")
        for value in forbidden:
            assert value not in rendered, (record.name, rendered)
