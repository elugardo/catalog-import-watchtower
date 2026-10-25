"""Spec section 9, scenarios 1 to 3, through the public HTTP API only (no SQL in assertions)."""

from tests.integration.contract import walk
from tests.integration.importing import fixture_bytes, post_import


def products(client, vendor_id: int):
    response = client.get("/api/products", params={"vendor_id": vendor_id})
    assert response.status_code == 200
    return response


def listed_import(client, import_id: int) -> dict:
    (item,) = [i for i in walk(client, "/api/imports") if i["id"] == import_id]
    return item


def test_happy_path_upsert_and_atomic_validation(client, ns):
    vendor = ns.name()

    # 1. Happy path.
    first = post_import(client, vendor, fixture_bytes("valid.csv"))
    assert first.status_code == 201
    vendor_id = first.json()["vendor"]["id"]
    body = products(client, vendor_id).json()
    assert body["total"] == 3
    by_sku = {item["sku"]: item for item in body["items"]}
    assert {sku: (p["price_cents"], p["quantity"]) for sku, p in by_sku.items()} == {
        "CHAIR-001": (14999, 8),
        "TABLE-002": (49900, 3),
        "LAMP-003": (3950, 12),
    }
    item = listed_import(client, first.json()["id"])
    assert (item["status"], item["attempt_count"]) == ("COMPLETED", 1)

    # 2. Upsert: same count, CHAIR-001 changed in place, the others untouched.
    second = post_import(client, vendor, fixture_bytes("update.csv"), filename="update.csv")
    assert second.json()["status"] == "COMPLETED"
    after = products(client, vendor_id).json()
    assert after["total"] == 3
    updated = {item["sku"]: item for item in after["items"]}
    assert (updated["CHAIR-001"]["price_cents"], updated["CHAIR-001"]["quantity"]) == (12999, 20)
    assert updated["CHAIR-001"]["id"] == by_sku["CHAIR-001"]["id"]
    for sku in ("TABLE-002", "LAMP-003"):
        assert updated[sku] == by_sku[sku]

    # 3. Atomic validation: the failed import changes nothing at all.
    before = products(client, vendor_id).text
    failed = post_import(client, vendor, fixture_bytes("invalid.csv"), filename="invalid.csv")
    assert failed.status_code == 201
    assert failed.json()["status"] == "FAILED"
    errors = failed.json()["validation_errors"]
    assert any(e["line"] == 4 and e["column"] == "quantity" for e in errors), errors
    assert listed_import(client, failed.json()["id"])["status"] == "FAILED"
    assert products(client, vendor_id).text == before
