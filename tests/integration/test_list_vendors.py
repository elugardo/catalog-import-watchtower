"""`GET /api/vendors` (spec section 7): `{id, display_name}`, newest first, ties by `id` descending."""

from tests.integration.contract import assert_matches, sql, walk
from tests.integration.importing import fixture_bytes, post_import


def test_order_is_created_at_descending_then_id_descending(client, migrated_engine, ns):
    ids = [
        post_import(client, ns.name(label), fixture_bytes("valid.csv")).json()["vendor"]["id"]
        for label in ("Vendor A", "Vendor B", "Vendor C")
    ]
    a, b, c = ids
    # A newest; B and C tied. By id alone the order would be C, B, A.
    sql(
        migrated_engine,
        "UPDATE vendors SET created_at = CASE id"
        " WHEN :a THEN now() - interval '1 hour'"
        " ELSE now() - interval '2 hours' END WHERE id IN (:a, :b, :c)",
        a=a,
        b=b,
        c=c,
    )

    listed = walk(client, "/api/vendors")

    for item in listed:
        assert set(item) == {"id", "display_name"}
    assert [item["id"] for item in listed if item["id"] in set(ids)] == [a, c, b]


def test_a_vendor_whose_only_import_failed_is_listed(client, ns):
    created = post_import(
        client, ns.name(), fixture_bytes("invalid.csv"), filename="invalid.csv"
    ).json()
    assert created["status"] == "FAILED"

    listed = {item["id"]: item for item in walk(client, "/api/vendors")}

    assert listed[created["vendor"]["id"]] == {
        "id": created["vendor"]["id"],
        "display_name": ns.name(),
    }


def test_two_spellings_are_one_vendor_with_the_first_spelling(client, ns):
    first = post_import(client, f" {ns.name()} ", fixture_bytes("valid.csv")).json()
    second = post_import(client, ns.name().lower(), fixture_bytes("update.csv")).json()
    assert first["vendor"]["id"] == second["vendor"]["id"]

    response = client.get("/api/vendors", params={"limit": 100})
    assert_matches(response.json(), "VendorList")
    ours = [item for item in walk(client, "/api/vendors") if ns.token in item["display_name"]]

    assert ours == [{"id": first["vendor"]["id"], "display_name": f"Sample Furnishings {ns.token}"}]
