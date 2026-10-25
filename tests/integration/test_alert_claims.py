"""The worker's claim helpers in `app/services/alerts.py` (#10; used by #11).

Neither is a tool: they write no `agent_actions` row. `reset_stale_claims`
touches every `IN_PROGRESS` alert of the database, so its test runs on
`isolated_db`.
"""

import pytest
from sqlalchemy import text

from app.db import get_sessionmaker
from app.services import alerts
from tests.integration.conftest import Namespace
from tests.integration.test_import_sweep import insert_import
from tests.integration.tooling import (
    action_count,
    alert_row,
    barrier_before,
    claim,
    injected,
    run_concurrently,
    set_alert_status,
)


def test_claim_takes_an_open_alert_once(client, migrated_engine, ns):
    alert_id = injected(client, ns.name())["alert"]["id"]
    before = alert_row(migrated_engine, alert_id)
    actions = action_count(migrated_engine)

    assert claim(alert_id) is True
    assert claim(alert_id) is False

    after = alert_row(migrated_engine, alert_id)
    assert after["status"] == "IN_PROGRESS"
    assert after["claimed_at"] is not None and before["claimed_at"] is None
    assert (after["reason"], after["created_at"]) == (before["reason"], before["created_at"])
    assert action_count(migrated_engine) == actions


def test_two_concurrent_claims_one_wins(client, migrated_engine, ns, monkeypatch):
    alert_id = injected(client, ns.name())["alert"]["id"]
    barrier_before(monkeypatch, alerts, "claim_alert", 2)

    results = run_concurrently(lambda: claim(alert_id), lambda: claim(alert_id))

    assert sorted(results) == [False, True]


@pytest.mark.parametrize("status", ["IN_PROGRESS", "NEEDS_ATTENTION", "RESOLVED"])
def test_claim_of_a_taken_alert_changes_nothing(client, migrated_engine, ns, status):
    alert_id = injected(client, ns.name())["alert"]["id"]
    set_alert_status(migrated_engine, alert_id, status)
    before = alert_row(migrated_engine, alert_id)

    assert claim(alert_id) is False
    assert alert_row(migrated_engine, alert_id) == before


@pytest.mark.parametrize("value", [0, -1, 2**63, 2**63 - 1], ids=str)
def test_claim_of_an_unknown_alert_is_negative(client, value):
    assert claim(value) is False


def test_reset_stale_claims_returns_only_old_claims_to_open(isolated_db):
    _, engine = isolated_db  # the app's engine points at it too
    ns = Namespace(engine)
    with engine.begin() as connection:
        vendor_id = connection.execute(
            text(
                "INSERT INTO vendors (display_name, normalized_name) VALUES (:n, :n) RETURNING id"
            ),
            {"n": ns.name().casefold()},
        ).scalar_one()
        seeded = {}
        for label, status, claimed_ago in [
            ("stale", "IN_PROGRESS", "10 minutes"),
            ("stale too", "IN_PROGRESS", "301 seconds"),
            ("fresh", "IN_PROGRESS", "10 seconds"),
            ("open", "OPEN", None),
            ("needs attention", "NEEDS_ATTENTION", "1 hour"),
            ("resolved", "RESOLVED", "1 hour"),
        ]:
            import_id = insert_import(connection, vendor_id, "FAILED", "TRANSIENT_STORAGE_TIMEOUT")
            seeded[label] = connection.execute(
                text(
                    "INSERT INTO alerts (import_id, status, reason, claimed_at) VALUES (:i, :s,"
                    " 'reason', now() - CAST(:ago AS interval)) RETURNING id"
                ),
                {"i": import_id, "s": status, "ago": claimed_ago},
            ).scalar_one()
    before = {label: alert_row(engine, alert_id) for label, alert_id in seeded.items()}

    with get_sessionmaker()() as session, session.begin():
        reset = alerts.reset_stale_claims(session, 300)

    assert reset == sorted([seeded["stale"], seeded["stale too"]])
    for label in ("stale", "stale too"):
        row = alert_row(engine, seeded[label])
        assert (row["status"], row["claimed_at"]) == ("OPEN", None)
        assert row["updated_at"] > before[label]["updated_at"]
    for label in ("fresh", "open", "needs attention", "resolved"):
        assert alert_row(engine, seeded[label]) == before[label], label
    assert action_count(engine) == 0
