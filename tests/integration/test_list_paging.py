"""The valid `limit` / `offset` values of all four lists, and `total` against SQL (spec section 7).

Each test first makes sure every table holds at least two rows of its own
(an import that completed, one that failed with an alert), then compares with
a SQL `count(*)` taken right before or after, so the rows already in a shared
database do not matter.
"""

import pytest

from tests.integration.contract import assert_matches, sql, sql_count
from tests.integration.importing import fixture_bytes, post_import

TABLES = {
    "/api/imports": ("imports", "ImportList"),
    "/api/vendors": ("vendors", "VendorList"),
    "/api/products": ("products", "ProductList"),
    "/api/alerts": ("alerts", "AlertList"),
}
BEYOND_BIGINT = ["9223372036854775808", "99999999999999999999"]


@pytest.fixture
def rows(client, migrated_engine, ns) -> dict[str, int]:
    valid = post_import(client, ns.name("Vendor A"), fixture_bytes("valid.csv")).json()
    failed = post_import(
        client, ns.name("Vendor B"), fixture_bytes("invalid.csv"), filename="invalid.csv"
    ).json()
    for import_id in (valid["id"], failed["id"]):
        sql(
            migrated_engine,
            "INSERT INTO alerts (import_id, status, reason) VALUES (:i, 'OPEN', 'test')",
            i=import_id,
        )
    return {"vendor_id": valid["vendor"]["id"]}


@pytest.mark.parametrize("path", TABLES)
def test_limit_one_and_the_true_total(client, migrated_engine, rows, path):
    table, envelope = TABLES[path]

    body = client.get(path, params={"limit": 1}).json()

    assert_matches(body, envelope)
    assert len(body["items"]) == 1
    assert body["total"] == sql_count(migrated_engine, table)
    assert body["total"] >= 2


@pytest.mark.parametrize("path", TABLES)
def test_limit_100_and_leading_zeros_are_accepted(client, rows, path):
    hundred = client.get(path, params={"limit": 100})
    assert hundred.status_code == 200
    assert len(hundred.json()["items"]) == min(100, hundred.json()["total"])

    assert client.get(f"{path}?limit=05").json() == client.get(f"{path}?limit=5").json()
    assert len(client.get(f"{path}?limit=05").json()["items"]) == min(5, hundred.json()["total"])


@pytest.mark.parametrize("path", TABLES)
def test_no_parameters_equals_limit_50_offset_0_and_unknown_ones_are_ignored(client, rows, path):
    plain = client.get(path).json()

    assert plain == client.get(f"{path}?limit=50&offset=0").json()
    assert plain == client.get(f"{path}?foo=1").json()
    assert len(plain["items"]) == min(50, plain["total"])


@pytest.mark.parametrize("path", TABLES)
def test_offset_at_and_just_before_the_end(client, migrated_engine, rows, path):
    table, _ = TABLES[path]
    total = client.get(path, params={"limit": 1}).json()["total"]

    at_end = client.get(path, params={"offset": total}).json()
    last = client.get(path, params={"offset": total - 1}).json()

    assert at_end == {"items": [], "total": total}
    assert len(last["items"]) == 1 and last["total"] == total
    assert total == sql_count(migrated_engine, table)


@pytest.mark.parametrize("path", TABLES)
@pytest.mark.parametrize("offset", BEYOND_BIGINT)
def test_offset_beyond_bigint_is_an_empty_page_never_500(
    client, migrated_engine, rows, path, offset
):
    table, _ = TABLES[path]

    response = client.get(f"{path}?offset={offset}")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total": sql_count(migrated_engine, table)}


def test_products_total_under_the_vendor_filter(client, migrated_engine, rows):
    vendor_id = rows["vendor_id"]
    expected = sql_count(migrated_engine, "products", "vendor_id = :v", v=vendor_id)

    paged = client.get("/api/products", params={"vendor_id": vendor_id, "limit": 1}).json()
    past = client.get(f"/api/products?vendor_id={vendor_id}&offset={BEYOND_BIGINT[1]}").json()

    assert expected == 3
    assert paged["total"] == expected and len(paged["items"]) == 1
    assert past == {"items": [], "total": expected}


def test_health_body_is_exactly_the_health_schema(client):
    body = client.get("/api/health").json()

    assert_matches(body, "Health")
    assert body["status"] == "ok"
