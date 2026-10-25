"""`GET /api/imports` (spec section 7): newest first, paged, each item the detail minus three keys.

The database may already hold other rows (the Compose `db` after a demo, or
QA's own uploads), so every assertion is on the test's own rows, or on a SQL
`count(*)` taken at the same moment.
"""

import hashlib

from tests.integration.contract import assert_matches, item_keys, sql, sql_count, walk
from tests.integration.importing import HEADER, csv_rows, fixture_bytes, post_import

DETAIL_ONLY = ("attempts", "alert", "agent_actions")


def tiny_csv(n: int) -> bytes:
    return HEADER + csv_rows(1, prefix=f"IMP{n}")


def test_default_page_is_the_newest_50_and_limit_100_holds_all_51(client, migrated_engine, ns):
    vendor = ns.name()
    created = [post_import(client, vendor, tiny_csv(n)).json()["id"] for n in range(51)]
    newest_first = list(reversed(created))

    default = client.get("/api/imports")
    assert default.status_code == 200
    body = default.json()
    assert_matches(body, "ImportList")
    assert [item["id"] for item in body["items"]] == newest_first[:50]
    assert body["total"] == sql_count(migrated_engine, "imports")

    hundred = client.get("/api/imports", params={"limit": 100}).json()
    ours = [item["id"] for item in hundred["items"] if item["id"] in set(created)]
    assert ours == newest_first


def test_order_is_created_at_descending_then_id_descending(client, migrated_engine, ns):
    vendor = ns.name()
    first, second, third = (post_import(client, vendor, tiny_csv(n)).json()["id"] for n in range(3))
    # created_at order: first (newest), then second and third tied. By id alone
    # the order would be third, second, first; with `id ASC` on the tie, second
    # would come before third.
    sql(
        migrated_engine,
        "UPDATE imports SET created_at = CASE id"
        " WHEN :a THEN now() - interval '1 hour'"
        " ELSE now() - interval '2 hours' END WHERE id IN (:a, :b, :c)",
        a=first,
        b=second,
        c=third,
    )

    listed = [item["id"] for item in walk(client, "/api/imports")]

    ours = [i for i in listed if i in {first, second, third}]
    assert ours == [first, third, second]


def insert_vendor(engine, ns, label: str) -> int:
    name = ns.name(label)
    return sql(
        engine,
        "INSERT INTO vendors (display_name, normalized_name) VALUES (:d, :n) RETURNING id",
        d=name,
        n=name.casefold(),
    )[0].id


def insert_processing_import(engine, vendor_id: int, *, with_attempt: bool) -> int:
    data = HEADER + csv_rows(1)
    import_id = sql(
        engine,
        "INSERT INTO imports (vendor_id, filename, csv_bytes, sha256, status)"
        " VALUES (:v, 'stuck.csv', :b, :s, 'PROCESSING') RETURNING id",
        v=vendor_id,
        b=data,
        s=hashlib.sha256(data).hexdigest(),
    )[0].id
    if with_attempt:
        sql(
            engine,
            "INSERT INTO import_attempts (import_id, attempt_number, status)"
            " VALUES (:i, 1, 'RUNNING')",
            i=import_id,
        )
    return import_id


def test_a_list_item_is_the_detail_without_its_three_embedded_keys(client, migrated_engine, ns):
    vendor = ns.name()
    valid = post_import(client, vendor, fixture_bytes("valid.csv")).json()["id"]
    invalid = post_import(
        client, vendor, fixture_bytes("invalid.csv"), filename="invalid.csv"
    ).json()["id"]
    recovered = post_import(client, vendor, fixture_bytes("valid.csv")).json()["id"]
    sql(
        migrated_engine,
        "INSERT INTO import_attempts (import_id, attempt_number, status, finished_at)"
        " VALUES (:i, 2, 'SUCCEEDED', now())",
        i=recovered,
    )
    vendor_id = insert_vendor(migrated_engine, ns, "Stuck Vendor")
    running = insert_processing_import(migrated_engine, vendor_id, with_attempt=True)
    no_attempt = insert_processing_import(migrated_engine, vendor_id, with_attempt=False)

    listed = {item["id"]: item for item in walk(client, "/api/imports")}

    for import_id in (valid, invalid, recovered, running, no_attempt):
        item = listed[import_id]
        detail = client.get(f"/api/imports/{import_id}").json()
        for key in DETAIL_ONLY:
            detail.pop(key)
        assert item == detail, import_id
        assert set(item) == item_keys("Import")
        assert "csv_bytes" not in item
        assert_matches(item, "Import")

    assert (listed[valid]["status"], listed[valid]["attempt_count"]) == ("COMPLETED", 1)
    assert listed[valid]["recovered"] is False
    assert listed[invalid]["status"] == "FAILED"
    assert listed[invalid]["validation_errors"]
    assert listed[invalid]["validation_error_count"] == len(listed[invalid]["validation_errors"])
    assert (listed[recovered]["attempt_count"], listed[recovered]["recovered"]) == (2, True)
    assert listed[running]["status"] == "PROCESSING"
    assert listed[running]["attempt_count"] == 1
    assert listed[running]["product_count"] is None
    assert listed[running]["completed_at"] is None
    assert listed[running]["recovered"] is False
    assert listed[no_attempt]["attempt_count"] == 0
