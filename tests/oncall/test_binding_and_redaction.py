"""A run touches only its claimed alert, and only redacted operational facts reach the provider."""

import json
import logging
import os

import pytest

from tests.integration.importing import import_row
from tests.integration.tooling import (
    action_rows,
    alert_row,
    attempt_rows,
    injected,
    upload,
)
from tests.oncall import fake_llm as fake
from tests.oncall.helpers import run_claimed

CANARY = "CANARYQZ71"


def ids(body: dict) -> tuple[int, int]:
    return body["alert"]["id"], body["id"]


def snapshot(engine, body: dict) -> dict:
    alert_id, import_id = ids(body)
    return {
        "import": import_row(engine, import_id),
        "attempts": attempt_rows(engine, import_id),
        "alert": alert_row(engine, alert_id),
        "actions": action_rows(engine, alert_id),
    }


def test_a_run_acts_only_on_its_claimed_alert(client, migrated_engine, ns):
    a = injected(client, ns.name("Vendor A"))
    b = injected(client, ns.name("Vendor B"))
    a_alert, a_import = ids(a)
    b_alert, b_import = ids(b)
    b_before = snapshot(migrated_engine, b)
    model = fake.FakeAnthropic(
        [
            fake.call("get_import_incident", alert_id=b_alert),
            fake.call("get_import_attempts", import_id=b_import),
            fake.call("retry_failed_import", import_id=b_import),
            fake.call("resolve_alert", alert_id=b_alert),
            fake.call("mark_needs_attention", alert_id=b_alert, reason="foreign"),
            fake.call("get_import_incident", alert_id=a_alert),
            fake.call("mark_needs_attention", alert_id=a_alert, reason="escalating A"),
        ]
    )

    summary = run_claimed(model, a_alert, a_import)

    # B and its import are untouched: no attempt, no status change, no timeline row.
    assert snapshot(migrated_engine, b) == b_before
    # Each foreign call got the same fixed-text error and counted toward the limit.
    results = model.tool_results()
    refusal = {
        "error": f"refused: this run may act only on alert {a_alert} and its import {a_import}"
    }
    assert [json.loads(r["content"]) for r in results[:5]] == [refusal] * 5
    assert all(r["is_error"] for r in results[:5])
    assert summary.tool_calls == 7
    # Nothing the model received names B: the only real result is A's incident.
    incident = json.loads(results[5]["content"])
    assert (incident["alert_id"], incident["import_id"]) == (a_alert, a_import)
    for result in results:
        parsed = json.loads(result["content"])
        assert parsed.get("alert_id") in (None, a_alert)
        assert parsed.get("import_id") in (None, a_import)
    # The refusals are recorded on A's timeline.
    a_rows = [r for r in action_rows(migrated_engine, a_alert) if r["action"] == "TOOL_CALL"]
    refused = [r for r in a_rows if (r["reason_summary"] or "").startswith("refused by the worker")]
    assert [r["tool_name"] for r in refused] == [
        "get_import_incident",
        "get_import_attempts",
        "retry_failed_import",
        "resolve_alert",
        "mark_needs_attention",
    ]
    assert alert_row(migrated_engine, a_alert)["status"] == "NEEDS_ATTENTION"
    assert len(attempt_rows(migrated_engine, a_import)) == 1


def canary_csv() -> bytes:
    return (
        "sku,name,price,quantity\n"
        f"{CANARY}-SKU-1,{CANARY} Velvet Sofa,12.34,2\n"
        f"{CANARY}-SKU-2,{CANARY} Walnut Shelf,5.00,7\n"
    ).encode()


def canary_invalid_csv() -> bytes:
    return (
        "sku,name,price,quantity\n"
        f"{CANARY}-SKU-1,{CANARY} Velvet Sofa,{CANARY}-price,2\n"
        f"{CANARY}-SKU-1,{CANARY} Walnut Shelf,5.00,{CANARY}-qty\n"
    ).encode()


@pytest.mark.parametrize("kind", ["injected", "validation"])
def test_no_catalog_content_or_environment_value_reaches_the_provider(
    client, migrated_engine, ns, monkeypatch, caplog, kind
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", f"{CANARY}-provider-key-value")
    vendor = ns.name(f"{CANARY} Vendor")
    if kind == "injected":
        body = upload(client, vendor, canary_csv(), filename=f"{CANARY}-file.csv", inject="true")
    else:
        body = upload(client, vendor, canary_invalid_csv(), filename=f"{CANARY}-file.csv")
        assert body["failure_code"] == "VALIDATION_ERROR"
    alert_id, import_id = ids(body)
    model = fake.FakeAnthropic(
        [
            fake.call("get_import_incident", alert_id=alert_id),
            fake.call("get_import_attempts", import_id=import_id),
            fake.call("get_import_diagnostics", import_id=import_id),
            fake.call("retry_failed_import", import_id=import_id),
            fake.text("done"),
        ]
    )
    caplog.set_level(logging.DEBUG)

    run_claimed(model, alert_id, import_id)

    sent = model.sent()
    assert len(model.tool_results()) == 4  # the tool results did reach the model
    assert CANARY not in sent
    for value in os.environ.values():
        if len(value) >= 16:
            assert value not in sent
    assert CANARY not in caplog.text
    for row in action_rows(migrated_engine, alert_id):
        assert CANARY not in json.dumps(row, default=str)
