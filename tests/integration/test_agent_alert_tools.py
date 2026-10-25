"""`mark_needs_attention` and `resolve_alert` (#10; `_docs/team/oncall-agent.md` -> *Tool allowlist*).

Both are compare-and-set on the status read at the start of the call, and
commit their status change and their `TOOL_CALL` row in one transaction.
"""

import pytest

from app.services import agent_tools
from app.services.agent_tools import mark_needs_attention, resolve_alert, retry_failed_import
from tests.integration.tooling import (
    action_count,
    action_rows,
    alert_row,
    barrier_after,
    claim,
    injected,
    run_concurrently,
    set_alert_status,
)

REASON = "retry budget exhausted"
UNKNOWN_IDS = [0, -1, 2**63, 2**80, 2**63 - 1]


def recovered(client, ns) -> dict:
    """An injected import retried to `COMPLETED`; its alert is still `OPEN`."""
    body = injected(client, ns.name())
    assert retry_failed_import(body["id"])["import_status"] == "COMPLETED"
    return body


# ---- mark_needs_attention ------------------------------------------------------------------


def test_mark_needs_attention_moves_in_progress_to_needs_attention(client, migrated_engine, ns):
    body = injected(client, ns.name())
    alert_id = body["alert"]["id"]
    assert claim(alert_id)
    before = alert_row(migrated_engine, alert_id)

    result = mark_needs_attention(alert_id, f"  {REASON}  ")

    assert (result["outcome"], result["alert_status"]) == ("DONE", "NEEDS_ATTENTION")
    assert list(result) == ["outcome", *agent_tools.INCIDENT_KEYS]
    after = alert_row(migrated_engine, alert_id)
    assert (after["status"], after["reason"]) == ("NEEDS_ATTENTION", REASON)
    assert after["updated_at"] > before["updated_at"]
    assert (after["claimed_at"], after["created_at"]) == (
        before["claimed_at"],
        before["created_at"],
    )
    [action] = action_rows(migrated_engine, alert_id)
    assert (action["tool_name"], action["reason_summary"]) == ("mark_needs_attention", REASON)
    assert action["result"]["alert_status"] == "NEEDS_ATTENTION"


@pytest.mark.parametrize("status", ["OPEN", "RESOLVED", "NEEDS_ATTENTION"])
def test_mark_needs_attention_is_refused_unless_in_progress(client, migrated_engine, ns, status):
    alert_id = injected(client, ns.name())["alert"]["id"]
    set_alert_status(migrated_engine, alert_id, status)
    before = alert_row(migrated_engine, alert_id)

    result = mark_needs_attention(alert_id, REASON)

    assert (result["outcome"], result["refused_reason"]) == ("REFUSED", "alert_not_in_progress")
    assert result["alert_status"] == status
    assert alert_row(migrated_engine, alert_id) == before
    [action] = action_rows(migrated_engine, alert_id)
    assert action["result"]["refused_reason"] == "alert_not_in_progress"
    assert action["reason_summary"] is None


@pytest.mark.parametrize("reason", ["", "   ", "\t\n"], ids=["empty", "spaces", "whitespace"])
def test_a_blank_reason_is_refused(client, migrated_engine, ns, reason):
    alert_id = injected(client, ns.name())["alert"]["id"]
    assert claim(alert_id)
    before = alert_row(migrated_engine, alert_id)

    result = mark_needs_attention(alert_id, reason)

    assert (result["outcome"], result["refused_reason"]) == ("REFUSED", "empty_reason")
    assert alert_row(migrated_engine, alert_id) == before


def test_a_long_reason_is_cut_to_200_characters(client, migrated_engine, ns):
    alert_id = injected(client, ns.name())["alert"]["id"]
    assert claim(alert_id)
    reason = "".join(chr(ord("a") + n % 26) for n in range(201))

    assert mark_needs_attention(alert_id, f"  {reason} ")["outcome"] == "DONE"

    assert alert_row(migrated_engine, alert_id)["reason"] == reason[:200]
    assert action_rows(migrated_engine, alert_id)[0]["reason_summary"] == reason[:200]


# ---- resolve_alert ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["OPEN", "IN_PROGRESS", "NEEDS_ATTENTION"])
def test_resolve_alert_on_a_completed_import(client, migrated_engine, ns, status):
    alert_id = recovered(client, ns)["alert"]["id"]
    set_alert_status(migrated_engine, alert_id, status)
    before = alert_row(migrated_engine, alert_id)

    result = resolve_alert(alert_id)

    assert (result["outcome"], result["alert_status"], result["import_status"]) == (
        "DONE",
        "RESOLVED",
        "COMPLETED",
    )
    after = alert_row(migrated_engine, alert_id)
    assert after["status"] == "RESOLVED"
    assert after["updated_at"] > before["updated_at"]
    assert (after["reason"], after["claimed_at"], after["created_at"]) == (
        before["reason"],
        before["claimed_at"],
        before["created_at"],
    )
    assert action_rows(migrated_engine, alert_id)[-1]["tool_name"] == "resolve_alert"


def test_resolve_alert_is_refused_on_a_failed_import(client, migrated_engine, ns):
    """The "resolve_alert refused on a failed import" case of `_docs/testing.md`."""
    alert_id = injected(client, ns.name())["alert"]["id"]
    assert claim(alert_id)
    before = alert_row(migrated_engine, alert_id)

    result = resolve_alert(alert_id)

    assert (result["outcome"], result["refused_reason"]) == ("REFUSED", "import_not_completed")
    assert (result["import_status"], result["alert_status"]) == ("FAILED", "IN_PROGRESS")
    assert alert_row(migrated_engine, alert_id) == before
    [action] = action_rows(migrated_engine, alert_id)
    assert action["result"]["refused_reason"] == "import_not_completed"


def test_resolve_alert_is_refused_when_already_resolved(client, migrated_engine, ns):
    alert_id = recovered(client, ns)["alert"]["id"]
    assert resolve_alert(alert_id)["outcome"] == "DONE"
    before = alert_row(migrated_engine, alert_id)

    result = resolve_alert(alert_id)

    assert (result["outcome"], result["refused_reason"]) == ("REFUSED", "already_resolved")
    assert alert_row(migrated_engine, alert_id) == before


@pytest.mark.parametrize("value", UNKNOWN_IDS, ids=str)
def test_unknown_alerts_are_not_found(client, migrated_engine, value):
    before = action_count(migrated_engine)

    for result in (mark_needs_attention(value, REASON), resolve_alert(value)):
        assert result == {"outcome": "NOT_FOUND", "refused_reason": "not_found", "alert_id": value}

    assert action_count(migrated_engine) == before


# ---- compare-and-set ------------------------------------------------------------------------


def both_read_first(monkeypatch) -> None:
    """Both calls read the alert's status before either updates it."""
    barrier_after(monkeypatch, agent_tools, "_read_alert", 2)


def test_two_concurrent_marks_one_wins(client, migrated_engine, ns, monkeypatch):
    alert_id = injected(client, ns.name())["alert"]["id"]
    assert claim(alert_id)
    both_read_first(monkeypatch)

    results = run_concurrently(
        lambda: mark_needs_attention(alert_id, "first reason"),
        lambda: mark_needs_attention(alert_id, "second reason"),
    )

    assert sorted(r["outcome"] for r in results) == ["DONE", "REFUSED"]
    [winner] = [i for i, r in enumerate(results) if r["outcome"] == "DONE"]
    [loser] = [r for r in results if r["outcome"] == "REFUSED"]
    assert loser["refused_reason"] == "alert_not_in_progress"
    assert (
        alert_row(migrated_engine, alert_id)["reason"] == ["first reason", "second reason"][winner]
    )
    assert len(action_rows(migrated_engine, alert_id)) == 2


def test_two_concurrent_resolves_one_wins(client, migrated_engine, ns, monkeypatch):
    alert_id = recovered(client, ns)["alert"]["id"]
    both_read_first(monkeypatch)

    results = run_concurrently(lambda: resolve_alert(alert_id), lambda: resolve_alert(alert_id))

    assert sorted(r["outcome"] for r in results) == ["DONE", "REFUSED"]
    [loser] = [r for r in results if r["outcome"] == "REFUSED"]
    assert loser["refused_reason"] == "already_resolved"
    assert alert_row(migrated_engine, alert_id)["status"] == "RESOLVED"


def test_mark_and_resolve_at_once_one_wins(client, migrated_engine, ns, monkeypatch):
    alert_id = recovered(client, ns)["alert"]["id"]
    assert claim(alert_id)
    original_reason = alert_row(migrated_engine, alert_id)["reason"]
    both_read_first(monkeypatch)

    marked, resolved = run_concurrently(
        lambda: mark_needs_attention(alert_id, REASON), lambda: resolve_alert(alert_id)
    )

    assert sorted([marked["outcome"], resolved["outcome"]]) == ["DONE", "REFUSED"]
    after = alert_row(migrated_engine, alert_id)
    if marked["outcome"] == "DONE":
        assert (after["status"], after["reason"]) == ("NEEDS_ATTENTION", REASON)
        assert resolved["refused_reason"] == "alert_changed_concurrently"
    else:
        assert (after["status"], after["reason"]) == ("RESOLVED", original_reason)
        assert marked["refused_reason"] == "alert_not_in_progress"
