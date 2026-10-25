"""`retry_failed_import` (#10; spec sections 4 F5, 7 and 9 scenario 5).

The guard is read under `SELECT â€¦ FOR UPDATE` on the import row
(`_docs/architecture.md` -> *Import processing*, step 4). "Products snapshot"
is every product of every vendor (`all_products`).
"""

import threading

import pytest

from app.db import get_sessionmaker
from app.schemas.upload import UploadRequest
from app.services import agent_tools, alerts, importer
from app.services.agent_tools import resolve_alert, retry_failed_import
from app.services.importer import begin_attempt
from tests.integration.importing import alert_rows, all_products, import_row, products_by_sku
from tests.integration.tooling import (
    INVALID,
    VALID,
    action_rows,
    alert_row,
    attempt_rows,
    claim,
    force_real_operational_error,
    force_upsert_error,
    hold_lock_until_contended,
    injected,
    operational_error,
    paused,
    run_concurrently,
    upload,
)

VALID_VALUES = {
    "chair-001": ("CHAIR-001", "Oak Dining Chair", 14999, 8),
    "table-002": ("TABLE-002", "Round Dining Table", 49900, 3),
    "lamp-003": ("LAMP-003", "Desk Lamp", 3950, 12),
}


def product_values(engine, vendor_id: int) -> dict:
    return {
        key: (p["sku"], p["name"], p["price_cents"], p["quantity"])
        for key, p in products_by_sku(engine, vendor_id).items()
    }


def assert_recovered(engine, body: dict, result: dict) -> None:
    assert list(result) == ["outcome", *agent_tools.INCIDENT_KEYS]
    assert (result["outcome"], result["import_status"], result["failure_code"]) == (
        "DONE",
        "COMPLETED",
        None,
    )
    row = import_row(engine, body["id"])
    assert (row["status"], row["failure_code"], row["product_count"]) == ("COMPLETED", None, 3)
    assert row["completed_at"] is not None
    first, second = attempt_rows(engine, body["id"])
    assert (first["status"], first["error_code"]) == ("FAILED", "TRANSIENT_STORAGE_TIMEOUT")
    assert (second["attempt_number"], second["status"], second["error_code"]) == (
        2,
        "SUCCEEDED",
        None,
    )
    assert second["finished_at"] is not None
    assert product_values(engine, body["vendor"]["id"]) == VALID_VALUES


def test_the_fixture_values_are_what_valid_csv_holds(client, migrated_engine, ns):
    plain = upload(client, ns.name())
    assert product_values(migrated_engine, plain["vendor"]["id"]) == VALID_VALUES


def test_retry_recovers_an_injected_failure(client, migrated_engine, ns):
    body = injected(client, ns.name())
    stored = import_row(migrated_engine, body["id"])
    alert_before = alert_row(migrated_engine, body["alert"]["id"])

    result = retry_failed_import(body["id"])

    assert_recovered(migrated_engine, body, result)
    after = import_row(migrated_engine, body["id"])
    assert (after["sha256"], after["csv_bytes"]) == (stored["sha256"], stored["csv_bytes"])
    # Resolving is resolve_alert's job: the retry leaves the alert row alone.
    assert alert_row(migrated_engine, body["alert"]["id"]) == alert_before
    [action] = action_rows(migrated_engine, body["alert"]["id"])
    assert (action["action"], action["tool_name"]) == ("TOOL_CALL", "retry_failed_import")
    assert action["result"]["outcome"] == "DONE"


def test_retry_recovers_after_a_real_operational_error(client, migrated_engine, ns, monkeypatch):
    with monkeypatch.context() as patched:
        force_real_operational_error(patched)
        body = upload(client, ns.name())
    assert (body["status"], body["failure_code"]) == ("FAILED", "TRANSIENT_STORAGE_TIMEOUT")
    assert body["alert"]["reason"] == alerts.operational_reason(1)
    alert_before = alert_row(migrated_engine, body["alert"]["id"])

    result = retry_failed_import(body["id"])

    assert_recovered(migrated_engine, body, result)
    assert alert_row(migrated_engine, body["alert"]["id"]) == alert_before


# ---- refusals ----------------------------------------------------------------------------------


def _validation_error(client, ns, monkeypatch):
    return upload(client, ns.name(), INVALID, filename="invalid.csv")["id"]


def _internal_error(client, ns, monkeypatch):
    with monkeypatch.context() as patched:
        force_upsert_error(patched, RuntimeError("unexpected"))
        body = upload(client, ns.name())
    assert body["failure_code"] == "INTERNAL_ERROR"
    return body["id"]


def _completed_first_attempt(client, ns, monkeypatch):
    return upload(client, ns.name())["id"]


def _completed_after_retry(client, ns, monkeypatch):
    body = injected(client, ns.name())
    assert retry_failed_import(body["id"])["import_status"] == "COMPLETED"
    return body["id"]


def _processing_attempt_1_running(client, ns, monkeypatch):
    import_id = importer.create_import(
        UploadRequest(
            vendor_name=ns.name(), filename="valid.csv", data=VALID, inject_transient_failure=False
        )
    )
    with get_sessionmaker()() as session, session.begin():
        begin_attempt(session, import_id, 1)
    return import_id


def _two_attempts(client, ns, monkeypatch):
    body = injected(client, ns.name())
    with monkeypatch.context() as patched:
        force_upsert_error(patched, operational_error())
        assert retry_failed_import(body["id"])["import_status"] == "FAILED"
    return body["id"]


@pytest.mark.parametrize(
    ("prepare", "reason"),
    [
        (_validation_error, "not_transient"),
        (_internal_error, "not_transient"),
        (_completed_first_attempt, "import_not_failed"),
        (_completed_after_retry, "import_not_failed"),
        (_processing_attempt_1_running, "import_not_failed"),
        (_two_attempts, "retry_budget_exhausted"),
    ],
    ids=lambda v: getattr(v, "__name__", v).lstrip("_"),
)
def test_refusals_change_nothing(client, migrated_engine, ns, monkeypatch, prepare, reason):
    import_id = prepare(client, ns, monkeypatch)
    before = (
        import_row(migrated_engine, import_id),
        attempt_rows(migrated_engine, import_id),
        alert_rows(migrated_engine, import_id),
        all_products(migrated_engine),
    )
    alert = before[2][0] if before[2] else None
    actions_before = action_rows(migrated_engine, alert["id"]) if alert else []

    result = retry_failed_import(import_id)

    assert (result["outcome"], result["refused_reason"]) == ("REFUSED", reason)
    # The current state, as get_import_incident would return it.
    assert list(result) == ["outcome", "refused_reason", *agent_tools.INCIDENT_KEYS]
    assert result["import_status"] == before[0]["status"]
    assert result["attempt_count"] == len(before[1])
    assert result["alert_id"] == (alert["id"] if alert else None)
    after = (
        import_row(migrated_engine, import_id),
        attempt_rows(migrated_engine, import_id),
        alert_rows(migrated_engine, import_id),
        all_products(migrated_engine),
    )
    assert after == before
    if alert:
        actions = action_rows(migrated_engine, alert["id"])
        assert len(actions) == len(actions_before) + 1
        assert actions[-1]["result"]["refused_reason"] == reason
        assert actions[-1]["tool_name"] == "retry_failed_import"


# ---- concurrency -------------------------------------------------------------------------------


def test_two_concurrent_retries_make_one_attempt(client, migrated_engine, ns, monkeypatch):
    body = injected(client, ns.name())
    # Both calls are inside the tool, each with its own session, before either takes the
    # lock, and the one holding it commits only once the other is blocked on it.
    hold_lock_until_contended(monkeypatch, migrated_engine)

    results = run_concurrently(
        lambda: retry_failed_import(body["id"]), lambda: retry_failed_import(body["id"])
    )

    assert sorted(r["outcome"] for r in results) == ["DONE", "REFUSED"]
    [loser] = [r for r in results if r["outcome"] == "REFUSED"]
    assert loser["refused_reason"] == "import_not_failed"
    assert loser["import_status"] in {"PROCESSING", "COMPLETED"}
    assert len(attempt_rows(migrated_engine, body["id"])) == 2
    assert len(products_by_sku(migrated_engine, body["vendor"]["id"])) == 3
    actions = action_rows(migrated_engine, body["alert"]["id"])
    assert [a["tool_name"] for a in actions] == ["retry_failed_import"] * 2


# ---- attempt 2 fails ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "code", "reason", "next_refusal"),
    [
        (
            operational_error(),
            "TRANSIENT_STORAGE_TIMEOUT",
            alerts.operational_reason(2),
            "retry_budget_exhausted",
        ),
        (RuntimeError("unexpected"), "INTERNAL_ERROR", alerts.internal_reason(2), "not_transient"),
    ],
    ids=["OperationalError", "other exception"],
)
def test_a_failed_attempt_2(
    client, migrated_engine, ns, monkeypatch, exc, code, reason, next_refusal
):
    body = injected(client, ns.name())
    assert claim(body["alert"]["id"])
    alert_before = alert_row(migrated_engine, body["alert"]["id"])
    products_before = all_products(migrated_engine)

    with monkeypatch.context() as patched:
        force_upsert_error(patched, exc)
        result = retry_failed_import(body["id"])

    assert (result["outcome"], result["import_status"], result["failure_code"]) == (
        "DONE",
        "FAILED",
        code,
    )
    assert result["attempts"][1]["error_code"] == code
    row = import_row(migrated_engine, body["id"])
    assert (row["status"], row["failure_code"]) == ("FAILED", code)
    assert (row["completed_at"], row["product_count"]) == (None, None)
    second = attempt_rows(migrated_engine, body["id"])[1]
    assert (second["status"], second["error_code"]) == ("FAILED", code)
    assert second["finished_at"] is not None
    assert all_products(migrated_engine) == products_before
    [alert] = alert_rows(migrated_engine, body["id"])
    assert alert["id"] == alert_before["id"]
    assert alert["reason"] == reason
    assert alert["updated_at"] > alert_before["updated_at"]
    assert (alert["status"], alert["claimed_at"], alert["created_at"]) == (
        alert_before["status"],
        alert_before["claimed_at"],
        alert_before["created_at"],
    )

    again = retry_failed_import(body["id"])
    assert (again["outcome"], again["refused_reason"]) == ("REFUSED", next_refusal)
    assert len(attempt_rows(migrated_engine, body["id"])) == 2


# ---- attempt 2 starts from PROCESSING ----------------------------------------------------------


def test_attempt_2_starts_from_processing(client, migrated_engine, ns, monkeypatch):
    body = injected(client, ns.name())
    outcome: list[dict] = []

    # Pause inside attempt 2, after the locked transaction committed, before the upsert.
    with paused(monkeypatch, importer, "validate_csv") as pause:
        worker = threading.Thread(target=lambda: outcome.append(retry_failed_import(body["id"])))
        worker.start()
        pause.wait()

        row = import_row(migrated_engine, body["id"])
        assert (row["status"], row["failure_code"]) == ("PROCESSING", "TRANSIENT_STORAGE_TIMEOUT")
        attempts = attempt_rows(migrated_engine, body["id"])
        assert [(a["attempt_number"], a["status"]) for a in attempts] == [
            (1, "FAILED"),
            (2, "RUNNING"),
        ]

        concurrent = retry_failed_import(body["id"])
        assert (concurrent["outcome"], concurrent["refused_reason"]) == (
            "REFUSED",
            "import_not_failed",
        )
        assert concurrent["import_status"] == "PROCESSING"
        assert len(attempt_rows(migrated_engine, body["id"])) == 2

        early = resolve_alert(body["alert"]["id"])
        assert (early["outcome"], early["refused_reason"]) == ("REFUSED", "import_not_completed")
        assert alert_row(migrated_engine, body["alert"]["id"])["status"] == "OPEN"

        pause.release()
        worker.join(30)

    [result] = outcome
    assert_recovered(migrated_engine, body, result)
