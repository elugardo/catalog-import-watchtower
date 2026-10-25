"""Vendor find-or-create through `POST /api/imports` (spec section 4 F1, F2)."""

import threading

from sqlalchemy import text

from tests.integration.importing import fixture_bytes, post_import, products_snapshot

VALID = fixture_bytes("valid.csv")


def vendor_rows(engine, normalized: str) -> list[dict]:
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                text("SELECT * FROM vendors WHERE normalized_name = :n"), {"n": normalized}
            ).mappings()
        ]


def test_trimmed_name_and_case_insensitive_match_keep_the_first_spelling(
    client, migrated_engine, ns
):
    first = post_import(client, f" {ns.name('Sample Furnishings')} ", VALID).json()
    assert first["vendor"] == {"id": first["vendor"]["id"], "display_name": ns.name()}
    vendor_id = first["vendor"]["id"]

    for spelling in (ns.name("sample furnishings"), ns.name("SAMPLE FURNISHINGS") + " "):
        again = post_import(client, spelling, VALID).json()
        assert again["vendor"] == {"id": vendor_id, "display_name": ns.name()}

    rows = vendor_rows(migrated_engine, ns.name().casefold())
    assert len(rows) == 1
    assert rows[0]["display_name"] == ns.name()


def test_inner_whitespace_makes_a_different_vendor(client, ns):
    one = post_import(client, ns.name("Sample Furnishings"), VALID).json()
    two = post_import(client, ns.name("Sample  Furnishings"), VALID).json()
    assert one["vendor"]["id"] != two["vendor"]["id"]


def test_casefold_not_lower(client, migrated_engine, ns):
    # "ß".lower() is "ß" but "ß".casefold() is "ss": only casefold makes these one vendor.
    one = post_import(client, ns.name("Straße"), VALID).json()
    two = post_import(client, ns.name("STRASSE").upper(), VALID).json()
    assert one["vendor"]["id"] == two["vendor"]["id"]
    assert len(vendor_rows(migrated_engine, ns.name("strasse"))) == 1


def test_vendor_is_created_even_when_the_first_import_fails(client, migrated_engine, ns):
    body = post_import(client, ns.name(), fixture_bytes("invalid.csv"), filename="invalid.csv")
    body = body.json()
    assert body["status"] == "FAILED"
    vendor = vendor_rows(migrated_engine, ns.name().casefold())
    assert len(vendor) == 1
    assert products_snapshot(migrated_engine, vendor[0]["id"]) == []


def race_two_uploads(clients, name: str) -> list:
    """Both clients post `valid.csv` for `name` at once, released by a barrier."""
    barrier = threading.Barrier(2)
    responses: list = [None, None]
    errors: list[BaseException] = []

    def upload(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            responses[index] = post_import(clients[index], name, VALID)
        except BaseException as exc:  # noqa: BLE001 - reported by the caller
            errors.append(exc)

    threads = [threading.Thread(target=upload, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert errors == []
    return responses


def test_concurrent_first_uploads_create_one_vendor(make_client, database_url, migrated_engine, ns):
    # Several rounds, each a new vendor, to make the race between the two
    # vendor inserts likely; one round already fails without ON CONFLICT.
    for round_number in range(3):
        name = ns.name(f"Concurrent {round_number}")
        clients = [make_client(DATABASE_URL=database_url) for _ in range(2)]

        responses = race_two_uploads(clients, name)

        assert [r.status_code for r in responses] == [201, 201], [r.text for r in responses]
        bodies = [r.json() for r in responses]
        assert [b["status"] for b in bodies] == ["COMPLETED", "COMPLETED"]
        vendors = vendor_rows(migrated_engine, name.casefold())
        assert len(vendors) == 1
        vendor_id = vendors[0]["id"]
        assert {b["vendor"]["id"] for b in bodies} == {vendor_id}
        with migrated_engine.connect() as connection:
            imports = connection.execute(
                text("SELECT count(*) FROM imports WHERE vendor_id = :v"), {"v": vendor_id}
            ).scalar_one()
        assert imports == 2
        assert len(products_snapshot(migrated_engine, vendor_id)) == 3
