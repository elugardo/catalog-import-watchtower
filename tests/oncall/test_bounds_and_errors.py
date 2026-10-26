"""The run's bounds, provider errors, and how a run that did not decide is closed."""

import time

import anthropic
import httpx2
import pytest
from sqlalchemy import text

from app.oncall import llm
from app.services import agent_tools
from tests.integration.tooling import action_rows, alert_row, attempt_rows, injected
from tests.oncall import fake_llm as fake
from tests.oncall.helpers import run_claimed


def ids(body: dict) -> tuple[int, int]:
    return body["alert"]["id"], body["id"]


def kinds(engine, alert_id: int) -> list[str]:
    return [row["action"] for row in action_rows(engine, alert_id)]


def finished(engine, alert_id: int) -> dict:
    [row] = [r for r in action_rows(engine, alert_id) if r["action"] == "RUN_FINISHED"]
    return row


def test_a_model_that_never_stops_is_cut_at_the_call_budget(client, migrated_engine, ns):
    body = injected(client, ns.name())
    alert_id, import_id = ids(body)
    model = fake.FakeAnthropic(fake.forever(fake.call("get_import_incident", alert_id=alert_id)))

    summary = run_claimed(model, alert_id, import_id, max_tool_calls=3)

    assert (summary.outcome, summary.tool_calls) == ("NEEDS_ATTENTION", 3)
    assert len(model.requests) == 4  # the 4th response's call was not executed
    rows = action_rows(migrated_engine, alert_id)
    assert [r["tool_name"] for r in rows if r["action"] == "TOOL_CALL"] == [
        "get_import_incident"
    ] * 3 + ["mark_needs_attention"]
    alert = alert_row(migrated_engine, alert_id)
    assert (alert["status"], alert["reason"]) == ("NEEDS_ATTENTION", "agent run exceeded limits")
    assert finished(migrated_engine, alert_id)["result"]["tool_calls"] == 3


def test_a_stalled_provider_is_cut_at_the_time_budget(client, migrated_engine, ns):
    body = injected(client, ns.name())
    alert_id, import_id = ids(body)
    model = fake.FakeAnthropic(
        [fake.call("get_import_incident", alert_id=alert_id), fake.stall_then_timeout]
    )

    started = time.monotonic()
    summary = run_claimed(model, alert_id, import_id, timeout_seconds=1.5)
    elapsed = time.monotonic() - started

    assert summary.outcome == "NEEDS_ATTENTION"
    assert summary.close_reason == "agent run exceeded limits"
    first, second = (r["timeout"] for r in model.requests)
    assert first <= 1.5
    assert second < first  # the provider call gets only the time that is left
    assert elapsed < 5
    assert alert_row(migrated_engine, alert_id)["reason"] == "agent run exceeded limits"


def test_a_running_tool_call_is_not_interrupted(client, migrated_engine, ns, monkeypatch):
    body = injected(client, ns.name())
    alert_id, import_id = ids(body)
    original = agent_tools.TOOLS["get_import_incident"]

    def slow(alert_id):
        time.sleep(1.2)
        return original(alert_id)

    monkeypatch.setitem(agent_tools.TOOLS, "get_import_incident", slow)
    model = fake.FakeAnthropic(
        [
            fake.call("get_import_incident", alert_id=alert_id),
            fake.call("retry_failed_import", import_id=import_id),
        ]
    )

    summary = run_claimed(model, alert_id, import_id, timeout_seconds=1.0)

    assert summary.close_reason == "agent run exceeded limits"
    tools = [
        r["tool_name"] for r in action_rows(migrated_engine, alert_id) if r["action"] == "TOOL_CALL"
    ]
    assert tools == ["get_import_incident", "mark_needs_attention"]  # finished, then stopped
    assert len(model.requests) == 1
    assert len(attempt_rows(migrated_engine, import_id)) == 1


def _authentication_error(request):
    response = httpx2.Response(401, request=httpx2.Request("POST", "https://fake.invalid/v1"))
    raise anthropic.AuthenticationError("fake secret detail", response=response, body=None)


def _rate_limit_error(request):
    response = httpx2.Response(429, request=httpx2.Request("POST", "https://fake.invalid/v1"))
    raise anthropic.RateLimitError("fake secret detail", response=response, body=None)


@pytest.mark.parametrize(
    ("step", "error_type"),
    [
        (fake.connection_error, "APIConnectionError"),
        (_authentication_error, "AuthenticationError"),
        (_rate_limit_error, "RateLimitError"),
    ],
    ids=["network", "authentication", "rate-limit"],
)
def test_a_provider_error_writes_error_with_the_type_only(
    client, migrated_engine, ns, step, error_type
):
    body = injected(client, ns.name())
    alert_id, import_id = ids(body)

    summary = run_claimed(fake.FakeAnthropic([step]), alert_id, import_id)

    assert summary.outcome == "NEEDS_ATTENTION"
    assert kinds(migrated_engine, alert_id) == ["RUN_STARTED", "ERROR", "TOOL_CALL", "RUN_FINISHED"]
    [error] = [r for r in action_rows(migrated_engine, alert_id) if r["action"] == "ERROR"]
    assert (error["reason_summary"], error["result"]) == (error_type, {"error_type": error_type})
    for row in action_rows(migrated_engine, alert_id):
        assert "fake.invalid" not in str(row["reason_summary"]) + str(row["result"])
        assert "detail" not in str(row["reason_summary"]) + str(row["result"])
        assert "network failure" not in str(row["reason_summary"]) + str(row["result"])
    alert = alert_row(migrated_engine, alert_id)
    assert (alert["status"], alert["reason"]) == (
        "NEEDS_ATTENTION",
        f"agent run failed ({error_type})",
    )


def test_a_text_only_reply_is_closed_as_no_decision(client, migrated_engine, ns):
    body = injected(client, ns.name())
    alert_id, import_id = ids(body)

    summary = run_claimed(
        fake.FakeAnthropic([fake.text("I think it is fine.")]), alert_id, import_id
    )

    assert (summary.outcome, summary.closed_by) == ("NEEDS_ATTENTION", "worker")
    alert = alert_row(migrated_engine, alert_id)
    assert (alert["status"], alert["reason"]) == ("NEEDS_ATTENTION", llm.REASON_NO_DECISION)
    assert kinds(migrated_engine, alert_id) == ["RUN_STARTED", "TOOL_CALL", "RUN_FINISHED"]
    started = action_rows(migrated_engine, alert_id)[0]
    assert started["result"] == {"provider": "anthropic", "model": "fake-model"}
    assert finished(migrated_engine, alert_id)["result"]["outcome"] == "NEEDS_ATTENTION"


def test_a_refused_closing_call_is_recorded_and_does_not_raise(client, migrated_engine, ns):
    body = injected(client, ns.name())
    alert_id, import_id = ids(body)

    def another_worker_resets_it(request):
        with migrated_engine.begin() as connection:
            connection.execute(
                text("UPDATE alerts SET status = 'OPEN', claimed_at = NULL WHERE id = :a"),
                {"a": alert_id},
            )
        return fake.text("Nothing to do.")

    summary = run_claimed(fake.FakeAnthropic([another_worker_resets_it]), alert_id, import_id)

    assert summary.close_refused_reason == "alert_not_in_progress"
    result = finished(migrated_engine, alert_id)["result"]
    assert result["close_refused_reason"] == "alert_not_in_progress"
    assert result["outcome"] == "OPEN"
    assert alert_row(migrated_engine, alert_id)["status"] == "OPEN"
