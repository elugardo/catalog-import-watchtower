"""`GET /api/products` (spec section 4 F3, section 7): the vendor filter, the order, paging.

Paging here is the contract the **Load more** control of #6 relies on:
request with `offset` = the items received so far until that equals `total`.
"""

import json

import pytest
from sqlalchemy import text

from tests.integration.contract import assert_matches, item_keys, sql_count, walk
from tests.integration.importing import HEADER, csv_rows, fixture_bytes, post_import


def upload(client, vendor: str, content: bytes, filename: str = "valid.csv") -> dict:
    response = post_import(client, vendor, content, filename=filename)
    assert response.status_code == 201, response.text
    return response.json()


def test_vendor_filter_and_unfiltered_total(client, migrated_engine, ns):
    a = upload(client, ns.name("Vendor A"), fixture_bytes("valid.csv"))["vendor"]["id"]
    b = upload(client, ns.name("Vendor B"), HEADER + csv_rows(2))["vendor"]["id"]

    only_a = client.get("/api/products", params={"vendor_id": a, "limit": 100}).json()
    assert_matches(only_a, "ProductList")
    assert only_a["total"] == 3
    assert {item["vendor_id"] for item in only_a["items"]} == {a}
    only_b = client.get("/api/products", params={"vendor_id": b}).json()
    assert only_b["total"] == 2
    assert {item["vendor_id"] for item in only_b["items"]} == {b}

    unfiltered = client.get("/api/products", params={"limit": 1}).json()
    assert unfiltered["total"] == sql_count(migrated_engine, "products")


def test_order_after_an_update_is_updated_at_then_id_descending(client, ns):
    vendor = ns.name()
    vendor_id = upload(client, vendor, fixture_bytes("valid.csv"))["vendor"]["id"]
    upload(client, vendor, fixture_bytes("update.csv"), "update.csv")

    body = client.get("/api/products", params={"vendor_id": vendor_id}).json()

    skus = [item["sku"] for item in body["items"]]
    ids = [item["id"] for item in body["items"]]
    # CHAIR-001 has the lowest id and the newest updated_at; the other two
    # share one updated_at and follow by id descending.
    assert skus == ["CHAIR-001", "LAMP-003", "TABLE-002"]
    assert ids[0] == min(ids)
    assert ids[1] > ids[2]


def test_items_have_exactly_the_product_properties_and_integer_money(client, ns):
    vendor_id = upload(client, ns.name(), fixture_bytes("valid.csv"))["vendor"]["id"]

    response = client.get("/api/products", params={"vendor_id": vendor_id})

    for item in response.json()["items"]:
        assert set(item) == item_keys("Product")
        assert "normalized_sku" not in item
        assert type(item["price_cents"]) is int
        assert type(item["quantity"]) is int
    chair = next(i for i in response.json()["items"] if i["sku"] == "CHAIR-001")
    assert (chair["price_cents"], chair["quantity"]) == (14999, 8)
    assert '"price_cents":14999,' in response.text.replace(" ", "")


@pytest.fixture
def five_hundred(client, ns) -> int:
    """One vendor with 500 products from one file, so all share one `updated_at`."""
    created = upload(client, ns.name(), HEADER + csv_rows(500))
    assert created["product_count"] == 500
    return created["vendor"]["id"]


def sql_order(engine, vendor_id: int) -> list[int]:
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    "SELECT id FROM products WHERE vendor_id = :v ORDER BY updated_at DESC, id DESC"
                ),
                {"v": vendor_id},
            ).scalars()
        )


def test_paging_over_one_import(client, migrated_engine, five_hundred):
    vendor_id = five_hundred

    tail = client.get("/api/products", params={"vendor_id": vendor_id, "offset": 450, "limit": 100})
    assert (len(tail.json()["items"]), tail.json()["total"]) == (50, 500)
    end = client.get("/api/products", params={"vendor_id": vendor_id, "offset": 500}).json()
    assert end == {"items": [], "total": 500}

    expected = sql_order(migrated_engine, vendor_id)
    for limit in (100, 50):
        walked: list[int] = []
        for offset in range(0, 500, limit):
            page = client.get(
                "/api/products", params={"vendor_id": vendor_id, "offset": offset, "limit": limit}
            ).json()
            assert page["total"] == 500
            walked.extend(item["id"] for item in page["items"])
        assert len(set(walked)) == 500, limit
        assert walked == expected, limit
    # The default limit walks the same way.
    default_walk: list[int] = []
    while len(default_walk) < 500:
        page = client.get(
            "/api/products", params={"vendor_id": vendor_id, "offset": len(default_walk)}
        ).json()
        assert len(page["items"]) == 50
        default_walk.extend(item["id"] for item in page["items"])
    assert default_walk == expected
    assert [item["id"] for item in walk(client, "/api/products", vendor_id=vendor_id)] == expected


@pytest.mark.parametrize("vendor_id", ["999999999", "0", "-1", "9223372036854775808"])
def test_unknown_or_impossible_vendor_id_is_an_empty_list(client, vendor_id):
    response = client.get(f"/api/products?vendor_id={vendor_id}")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0}


def test_a_vendor_without_products_is_an_empty_list(client, ns):
    created = upload(client, ns.name(), fixture_bytes("invalid.csv"), "invalid.csv")

    response = client.get("/api/products", params={"vendor_id": created["vendor"]["id"]})

    assert json.loads(response.text) == {"items": [], "total": 0}
