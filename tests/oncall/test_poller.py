"""The poll: claim, stale-claim reset, two workers, and scenario 4 end to end.

On `isolated_db`: a poll claims the oldest `OPEN` alert and resets every stale
claim in its database, so it must never run against rows it did not create.
"""

import pytest
from sqlalchemy import text

from app.oncall import poller
from app.services import agent_tools, alerts
from tests.integration.conftest import Namespace
from tests.integration.importing import products_by_sku
from tests.integration.tooling import (
    action_count,
    action_rows,
    alert_row,
    attempt_rows,
    barrier_before,
    force_upsert_error,
    injected,
    operational_error,
    run_concurrently,
)
from tests.oncall import fake_llm as fake
from tests.oncall.helpers import config


@pytest.fixture
def isolated(isolated_db, make_client):
    url, engine = isolated_db
    return make_client(DATABASE_URL=url), engine, Namespace(engine)


def recovery_script(alert_id: int, import_id: int) -> list:
    return [
        fake.call("get_import_incident", alert_id=alert_id),
        fake.call("retry_failed_import", import_id=import_id),
        fake.call("resolve_alert", "Attempt 2 completed; resolving.", alert_id=alert_id),
    ]


def make_stale(engine, alert_id: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE alerts SET status = 'IN_PROGRESS',"
                " claimed_at = now() - interval '1 hour' WHERE id = :a"
            ),
            {"a": alert_id},
        )


def test_scenario_4_end_to_end(isolated):
    client, engine, ns = isolated
    body = injected(client, ns.name())
    alert_id, import_id = body["alert"]["id"], body["id"]
    assert body["alert"]["status"] == "OPEN"
    assert products_by_sku(engine, body["vendor"]["id"]) == {}
    model = fake.FakeAnthropic(recovery_script(alert_id, import_id))

    summary = poller.poll_once(model, config())

    assert summary is not None and summary.outcome == "RESOLVED"
    detail = client.get(f"/api/imports/{import_id}").json()
    assert (detail["status"], detail["attempt_count"], detail["recovered"]) == (
        "COMPLETED",
        2,
        True,
    )
    assert [(a["number"], a["status"]) for a in detail["attempts"]] == [
        (1, "FAILED"),
        (2, "SUCCEEDED"),
    ]
    assert detail["alert"]["status"] == "RESOLVED"
    actions = [(a["action"], a["tool_name"]) for a in detail["agent_actions"]]
    assert actions[0] == ("RUN_STARTED", None)
    tool_calls = [name for kind, name in actions if kind == "TOOL_CALL"]
    assert tool_calls == ["get_import_incident", "retry_failed_import", "resolve_alert"]
    assert actions[-2:] == [("DECISION", "resolve_alert"), ("RUN_FINISHED", None)]
    decision = detail["agent_actions"][-2]
    assert decision["reason_summary"] == "Attempt 2 completed; resolving."
    assert detail["agent_actions"][0]["result"] == {"provider": "anthropic", "model": "fake-model"}
    finished = detail["agent_actions"][-1]["result"]
    assert (finished["outcome"], finished["tool_calls"]) == ("RESOLVED", 3)
    assert finished["duration_ms"] >= 0
    # Exactly 3 products, written once (attempt 1 wrote none).
    assert sorted(products_by_sku(engine, body["vendor"]["id"])) == [
        "chair-001",
        "lamp-003",
        "table-002",
    ]
    assert detail["product_count"] == 3


def test_a_poll_with_nothing_open_claims_nothing(isolated):
    _client, engine, _ns = isolated
    model = fake.FakeAnthropic([])

    assert poller.poll_once(model, config()) is None

    assert model.requests == []
    assert action_count(engine) == 0


def test_two_pollers_one_alert_exactly_one_claims(isolated, monkeypatch):
    client, engine, ns = isolated
    body = injected(client, ns.name())
    alert_id, import_id = body["alert"]["id"], body["id"]
    barrier_before(monkeypatch, alerts, "claim_alert", 2)  # both read the alert as OPEN first
    models = [fake.FakeAnthropic(recovery_script(alert_id, import_id)) for _ in range(2)]

    results = run_concurrently(*(lambda m=m: poller.poll_once(m, config()) for m in models))

    assert sorted(r is None for r in results) == [False, True]
    assert sorted(len(m.requests) for m in models) == [0, 3]
    kinds = [r["action"] for r in action_rows(engine, alert_id)]
    assert kinds.count("RUN_STARTED") == 1
    assert alert_row(engine, alert_id)["status"] == "RESOLVED"
    assert len(attempt_rows(engine, import_id)) == 2


def test_a_fresh_claim_is_left_alone(isolated):
    client, engine, ns = isolated
    body = injected(client, ns.name())
    alert_id = body["alert"]["id"]
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE alerts SET status = 'IN_PROGRESS', claimed_at = now() WHERE id = :a"),
            {"a": alert_id},
        )

    assert poller.poll_once(fake.FakeAnthropic([]), config()) is None

    assert alert_row(engine, alert_id)["status"] == "IN_PROGRESS"


def test_a_stale_claim_after_a_completed_retry_resolves(isolated):
    client, engine, ns = isolated
    body = injected(client, ns.name())
    alert_id, import_id = body["alert"]["id"], body["id"]
    assert agent_tools.retry_failed_import(import_id)["import_status"] == "COMPLETED"
    make_stale(engine, alert_id)  # the first worker died after the retry
    model = fake.FakeAnthropic(
        [
            fake.call("get_import_incident", alert_id=alert_id),
            fake.call("retry_failed_import", import_id=import_id),  # harmless: refused
            fake.call("resolve_alert", alert_id=alert_id),
        ]
    )

    summary = poller.poll_once(model, config(claim_timeout_seconds=300))

    assert summary is not None and summary.outcome == "RESOLVED"
    assert len(attempt_rows(engine, import_id)) == 2
    assert alert_row(engine, alert_id)["status"] == "RESOLVED"


def test_a_stale_claim_after_a_failed_attempt_2_ends_needs_attention(isolated, monkeypatch):
    client, engine, ns = isolated
    body = injected(client, ns.name())
    alert_id, import_id = body["alert"]["id"], body["id"]
    force_upsert_error(monkeypatch, operational_error())
    assert agent_tools.retry_failed_import(import_id)["import_status"] == "FAILED"
    make_stale(engine, alert_id)
    model = fake.FakeAnthropic(
        [
            fake.call("get_import_incident", alert_id=alert_id),
            fake.call("retry_failed_import", import_id=import_id),
            fake.call("mark_needs_attention", alert_id=alert_id, reason="retry budget exhausted"),
        ]
    )

    summary = poller.poll_once(model, config(claim_timeout_seconds=300))

    assert summary is not None and summary.outcome == "NEEDS_ATTENTION"
    assert len(attempt_rows(engine, import_id)) == 2
    alert = alert_row(engine, alert_id)
    assert (alert["status"], alert["reason"]) == ("NEEDS_ATTENTION", "retry budget exhausted")
    refused = [
        (r["result"] or {}).get("refused_reason")
        for r in action_rows(engine, alert_id)
        if r["tool_name"] == "retry_failed_import"
    ]
    assert refused[-1] == "retry_budget_exhausted"
