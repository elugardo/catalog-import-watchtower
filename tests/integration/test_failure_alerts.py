"""The durable failed-import alert (#7; spec section 4 F5, section 10 user-impact alert).

Every import that ends `FAILED` gets exactly one `alerts` row, written in the
transaction that sets `FAILED`. A later failure updates that row's `reason` and
`updated_at` only; a success never touches it. "Products snapshot" is every
product of every vendor (`importing.all_products`).
"""

import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.db import get_sessionmaker
from app.schemas.upload import UploadRequest
from app.services import alerts, importer
from tests.integration.contract import assert_matches, item_keys, sql, walk
from tests.integration.importing import (
    HEADER,
    alert_rows,
    all_products,
    fixture_bytes,
    post_import,
)

VALID = fixture_bytes("valid.csv")
INVALID = fixture_bytes("invalid.csv")


def upload(client, name, data, filename="valid.csv", **kwargs) -> dict:
    response = post_import(client, name, data, filename=filename, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()


def the_alert(engine, import_id: int) -> dict:
    (row,) = alert_rows(engine, import_id)
    return row


def assert_new_open_alert(body: dict, row: dict, reason: str) -> None:
    alert = body["alert"]
    assert alert is not None, body
    assert alert["id"] == row["id"]
    assert (alert["status"], alert["reason"], alert["claimed_at"]) == ("OPEN", reason, None)
    assert alert["created_at"] == alert["updated_at"]
    assert (row["status"], row["reason"], row["claimed_at"]) == ("OPEN", reason, None)
    assert row["created_at"] == row["updated_at"]


# ---- creation ------------------------------------------------------------------------


def test_scenario_3_creates_one_open_alert_with_the_validation_reason(client, migrated_engine, ns):
    upload(client, ns.name(), VALID)
    before = all_products(migrated_engine)

    body = upload(client, ns.name(), INVALID, filename="invalid.csv")

    assert (body["status"], body["failure_code"]) == ("FAILED", "VALIDATION_ERROR")
    count = body["validation_error_count"]
    assert count == 1
    reason = "VALIDATION_ERROR on attempt 1: 1 validation error"
    assert_new_open_alert(body, the_alert(migrated_engine, body["id"]), reason)
    assert client.get(f"/api/imports/{body['id']}").json()["alert"] == body["alert"]
    assert all_products(migrated_engine) == before


def test_validation_reason_counts_the_stored_total(client, migrated_engine, ns):
    data = HEADER + b"".join(f"Q-{n},Item {n},1.00,-1\n".encode() for n in range(25))

    body = upload(client, ns.name(), data)

    assert body["validation_error_count"] == 25
    assert body["alert"]["reason"] == "VALIDATION_ERROR on attempt 1: 25 validation errors"
    assert the_alert(migrated_engine, body["id"])["reason"] == body["alert"]["reason"]


def test_no_alert_on_success(client, migrated_engine, ns):
    body = upload(client, ns.name(), VALID)

    assert body["status"] == "COMPLETED"
    assert body["alert"] is None
    assert alert_rows(migrated_engine, body["id"]) == []


class Boom(RuntimeError):
    pass


def test_reasons_carry_no_content_and_stay_short(client, migrated_engine, monkeypatch, ns):
    vendor = ns.name("CANARYVENDOR7")
    filename = "CANARYFILE7.csv"
    invalid = HEADER + b"CANARYSKU7,CANARYNAME7,CANARYCELL7,1\n"
    valid = HEADER + b"CANARYSKU7,CANARYNAME7,1.00,1\n"
    reasons: list[str] = []

    validation = upload(client, vendor, invalid, filename=filename)
    injected = upload(client, vendor, valid, filename=filename, inject="true")
    assert validation["failure_code"] == "VALIDATION_ERROR"
    assert injected["failure_code"] == "TRANSIENT_STORAGE_TIMEOUT"
    reasons += [validation["alert"]["reason"], injected["alert"]["reason"]]

    def raising(exc):
        def failing_upsert(session, vendor_id, rows):
            raise exc(rows)

        return failing_upsert

    for exc, code in (
        (lambda rows: Boom(f"CANARYMSG7 {rows[0]['sku']} {rows[0]['name']}"), "INTERNAL_ERROR"),
        (
            lambda rows: OperationalError(
                f"UPDATE CANARYSQL7 {rows[0]['sku']}", {"n": rows[0]["name"]}, Boom("CANARYMSG7")
            ),
            "TRANSIENT_STORAGE_TIMEOUT",
        ),
    ):
        monkeypatch.setattr(importer, "_upsert_products", raising(exc))
        body = upload(client, vendor, valid, filename=filename)
        assert body["failure_code"] == code
        reasons.append(body["alert"]["reason"])

    assert len(reasons) == 4
    for reason in reasons:
        assert "CANARY" not in reason.upper(), reason
        assert ns.token not in reason
        assert "Boom" not in reason
        assert len(reason) <= 200
    assert reasons == [
        "VALIDATION_ERROR on attempt 1: 1 validation error",
        "TRANSIENT_STORAGE_TIMEOUT on attempt 1 (synthetic demo fault)",
        "INTERNAL_ERROR on attempt 1 (unexpected error)",
        "TRANSIENT_STORAGE_TIMEOUT on attempt 1 (database OperationalError)",
    ]


# ---- the update rule ---------------------------------------------------------------------


def claim(engine, alert_id: int) -> None:
    """What the worker's claim (#10) will do; here done by hand."""
    sql(
        engine,
        "UPDATE alerts SET status = 'IN_PROGRESS', claimed_at = now() - interval '1 minute'"
        " WHERE id = :a",
        a=alert_id,
    )


def test_a_failed_attempt_2_updates_the_same_alert_and_keeps_its_status(
    client, migrated_engine, monkeypatch, ns
):
    first = upload(client, ns.name(), VALID, inject="true")
    claim(migrated_engine, first["alert"]["id"])
    claimed = the_alert(migrated_engine, first["id"])

    def failing_upsert(session, vendor_id, rows):
        raise Boom("second failure")

    monkeypatch.setattr(importer, "_upsert_products", failing_upsert)
    importer.run_attempt(first["id"], 2)

    after = the_alert(migrated_engine, first["id"])
    assert after["id"] == claimed["id"]
    assert after["reason"] == "INTERNAL_ERROR on attempt 2 (unexpected error)"
    assert (after["status"], after["claimed_at"], after["created_at"]) == (
        "IN_PROGRESS",
        claimed["claimed_at"],
        claimed["created_at"],
    )
    assert after["updated_at"] > claimed["updated_at"]
    assert after["updated_at"] > after["created_at"]
    detail = client.get(f"/api/imports/{first['id']}").json()
    assert [(a["number"], a["status"], a["error_code"]) for a in detail["attempts"]] == [
        (1, "FAILED", "TRANSIENT_STORAGE_TIMEOUT"),
        (2, "FAILED", "INTERNAL_ERROR"),
    ]
    assert detail["alert"]["status"] == "IN_PROGRESS"


def test_a_success_never_touches_the_alert(client, migrated_engine, ns):
    injected = upload(client, ns.name(), VALID, inject="true")
    before = the_alert(migrated_engine, injected["id"])

    importer.run_attempt(injected["id"], 2)

    detail = client.get(f"/api/imports/{injected['id']}").json()
    assert detail["status"] == "COMPLETED"
    assert the_alert(migrated_engine, injected["id"]) == before
    assert before["status"] == "OPEN"
    assert before["reason"] == "TRANSIENT_STORAGE_TIMEOUT on attempt 1 (synthetic demo fault)"


# ---- concurrency -------------------------------------------------------------------------


def test_parallel_injected_uploads_each_get_their_own_alert(client, migrated_engine, ns):
    before = all_products(migrated_engine)
    vendors = [ns.name("Parallel A")] * 3 + [ns.name("Parallel B")] * 2

    with ThreadPoolExecutor(max_workers=5) as pool:
        responses = list(
            pool.map(lambda vendor: post_import(client, vendor, VALID, inject="true"), vendors)
        )

    bodies = [response.json() for response in responses]
    assert [response.status_code for response in responses] == [201] * 5
    for body in bodies:
        assert (body["status"], body["failure_code"]) == ("FAILED", "TRANSIENT_STORAGE_TIMEOUT")
        assert body["alert"]["status"] == "OPEN"
    import_ids = {body["id"] for body in bodies}
    assert len(import_ids) == 5
    alert_ids = {the_alert(migrated_engine, import_id)["id"] for import_id in import_ids}
    assert len(alert_ids) == 5
    assert all_products(migrated_engine) == before
    for vendor_id in {body["vendor"]["id"] for body in bodies}:
        assert client.get("/api/products", params={"vendor_id": vendor_id}).json()["total"] == 0
    assert len({body["vendor"]["id"] for body in bodies}) == 2


def test_two_writers_on_one_import_leave_one_row_and_neither_raises(migrated_engine, ns):
    import_id = importer.create_import(
        UploadRequest(
            vendor_name=ns.name(), filename="valid.csv", data=VALID, inject_transient_failure=False
        )
    )
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def write(reason: str) -> None:
        try:
            with get_sessionmaker()() as session, session.begin():
                session.execute(text("SELECT now()"))  # opens the transaction before the race
                barrier.wait(timeout=10)
                alerts.record_failure_alert(session, import_id, reason)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(alerts.internal_reason(n),)) for n in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    (row,) = alert_rows(migrated_engine, import_id)
    assert row["status"] == "OPEN"
    assert row["reason"] in {alerts.internal_reason(1), alerts.internal_reason(2)}
    assert row["updated_at"] > row["created_at"]


# ---- read side ---------------------------------------------------------------------------


def test_alerts_list_newest_first_with_the_import_summary(client, migrated_engine, ns):
    invalid = upload(client, ns.name("Reader A"), INVALID, filename="invalid.csv")
    injected = upload(client, ns.name("Reader B"), VALID, inject="true")
    ours = {invalid["alert"]["id"]: invalid, injected["alert"]["id"]: injected}

    listed = [item for item in walk(client, "/api/alerts") if item["id"] in ours]

    assert [item["id"] for item in listed] == [injected["alert"]["id"], invalid["alert"]["id"]]
    for item in listed:
        source = ours[item["id"]]
        assert set(item) == item_keys("AlertListItem")
        assert_matches(item, "AlertListItem")
        assert {k: item[k] for k in source["alert"]} == source["alert"]
        assert item["import_id"] == source["id"]
        assert item["import_status"] == "FAILED"
        assert item["failure_code"] == source["failure_code"]
        assert item["vendor_display_name"] == source["vendor"]["display_name"]
        assert item["filename"] == source["filename"]
        assert client.get(f"/api/imports/{source['id']}").json()["alert"] == source["alert"]


def test_no_endpoint_writes_an_alert(client):
    for method in ("POST", "PUT", "DELETE"):
        response = client.request(method, "/api/alerts")
        assert response.status_code == 405, method
        assert response.json()["code"] == "METHOD_NOT_ALLOWED"
