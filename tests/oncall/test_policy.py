"""The policy with scripted (and misbehaving) models: the guards hold, the alert ends where the
policy table of `_docs/team/oncall-agent.md` says. Real loop, dispatch and tools, real Postgres."""

import json

import pytest

from app.oncall import llm
from app.services import agent_tools
from tests.integration.importing import all_products, import_row
from tests.integration.tooling import (
    INVALID,
    action_rows,
    alert_row,
    attempt_rows,
    force_upsert_error,
    injected,
    operational_error,
    upload,
)
from tests.oncall import fake_llm as fake
from tests.oncall.helpers import run_claimed


def ids(body: dict) -> tuple[int, int]:
    return body["alert"]["id"], body["id"]


def tool_rows(engine, alert_id: int) -> list[tuple]:
    return [
        (
            row["tool_name"],
            (row["result"] or {}).get("outcome"),
            (row["result"] or {}).get("refused_reason"),
        )
        for row in action_rows(engine, alert_id)
        if row["action"] == "TOOL_CALL"
    ]


@pytest.fixture
def spy_tools(monkeypatch):
    """Counts every call the worker makes through `agent_tools.TOOLS`."""
    made: list[str] = []
    for name, function in list(agent_tools.TOOLS.items()):

        def wrapper(*args, _name=name, _function=function, **kwargs):
            made.append(_name)
            return _function(*args, **kwargs)

        monkeypatch.setitem(agent_tools.TOOLS, name, wrapper)
    return made


# ---- scenario 5: a validation error is never retried --------------------------------------


def test_scenario_5_validation_error_is_escalated_with_the_count(client, migrated_engine, ns):
    body = upload(client, ns.name(), INVALID, filename="invalid.csv")
    alert_id, import_id = ids(body)
    products_before = all_products(migrated_engine)

    def escalate(request):
        incident = json.loads(fake.tool_results_of(request)[0]["content"])
        count = incident["validation_error_count"]
        return fake.call(
            "mark_needs_attention",
            alert_id=alert_id,
            reason=f"VALIDATION_ERROR: {count} validation errors; needs corrected upload",
        )

    script = [
        fake.call("get_import_incident", alert_id=alert_id),
        fake.call("retry_failed_import", import_id=import_id),  # misbehaving: must be refused
        escalate,
    ]
    summary = run_claimed(fake.FakeAnthropic(script), alert_id, import_id)

    assert (summary.outcome, summary.closed_by) == ("NEEDS_ATTENTION", "model")
    alert = alert_row(migrated_engine, alert_id)
    assert alert["status"] == "NEEDS_ATTENTION"
    assert f"{body['validation_error_count']} validation errors" in alert["reason"]
    assert len(attempt_rows(migrated_engine, import_id)) == 1
    assert import_row(migrated_engine, import_id)["status"] == "FAILED"
    assert all_products(migrated_engine) == products_before
    assert ("retry_failed_import", "REFUSED", "not_transient") in tool_rows(
        migrated_engine, alert_id
    )


# ---- the retry asked for twice in one run -------------------------------------------------


@pytest.mark.parametrize("together", [False, True], ids=["one-per-turn", "two-in-one-turn"])
def test_a_second_retry_in_the_same_run_is_a_no_op(client, migrated_engine, ns, together):
    body = injected(client, ns.name())
    alert_id, import_id = ids(body)
    retry = [fake.call("retry_failed_import", import_id=import_id)]
    if together:
        twice = [
            fake.calls(
                fake.tool_use("retry_failed_import", {"import_id": import_id}),
                fake.tool_use("retry_failed_import", {"import_id": import_id}),
            )
        ]
    else:
        twice = retry + [fake.call("retry_failed_import", import_id=import_id)]
    script = [
        fake.call("get_import_incident", alert_id=alert_id),
        *twice,
        fake.call("resolve_alert", "Retry succeeded; resolving.", alert_id=alert_id),
    ]

    summary = run_claimed(fake.FakeAnthropic(script), alert_id, import_id)

    assert summary.outcome == "RESOLVED"
    assert [a["status"] for a in attempt_rows(migrated_engine, import_id)] == [
        "FAILED",
        "SUCCEEDED",
    ]
    retries = [r for r in tool_rows(migrated_engine, alert_id) if r[0] == "retry_failed_import"]
    assert retries == [
        ("retry_failed_import", "DONE", None),
        ("retry_failed_import", "REFUSED", "import_not_failed"),
    ]
    assert alert_row(migrated_engine, alert_id)["status"] == "RESOLVED"


# ---- a third attempt after two --------------------------------------------------------------


def test_a_third_attempt_is_refused(client, migrated_engine, ns, monkeypatch):
    body = injected(client, ns.name())
    alert_id, import_id = ids(body)
    force_upsert_error(monkeypatch, operational_error())
    assert agent_tools.retry_failed_import(import_id)["import_status"] == "FAILED"  # attempt 2
    script = [
        fake.call("get_import_incident", alert_id=alert_id),
        fake.call("retry_failed_import", import_id=import_id),
        fake.call("mark_needs_attention", alert_id=alert_id, reason="retry budget exhausted"),
    ]

    summary = run_claimed(fake.FakeAnthropic(script), alert_id, import_id)

    assert summary.outcome == "NEEDS_ATTENTION"
    assert len(attempt_rows(migrated_engine, import_id)) == 2
    assert ("retry_failed_import", "REFUSED", "retry_budget_exhausted") in tool_rows(
        migrated_engine, alert_id
    )
    alert = alert_row(migrated_engine, alert_id)
    assert (alert["status"], alert["reason"]) == ("NEEDS_ATTENTION", "retry budget exhausted")


# ---- resolve_alert on a FAILED import -------------------------------------------------------


def test_resolve_on_a_failed_import_is_refused_and_the_run_ends_needs_attention(
    client, migrated_engine, ns
):
    body = injected(client, ns.name())
    alert_id, import_id = ids(body)
    script = [
        fake.call("get_import_incident", alert_id=alert_id),
        fake.call("resolve_alert", alert_id=alert_id),
        fake.text("All done."),
    ]

    summary = run_claimed(fake.FakeAnthropic(script), alert_id, import_id)

    assert (summary.outcome, summary.closed_by) == ("NEEDS_ATTENTION", "worker")
    assert ("resolve_alert", "REFUSED", "import_not_completed") in tool_rows(
        migrated_engine, alert_id
    )
    alert = alert_row(migrated_engine, alert_id)
    assert (alert["status"], alert["reason"]) == ("NEEDS_ATTENTION", llm.REASON_NO_DECISION)
    assert import_row(migrated_engine, import_id)["status"] == "FAILED"
    assert len(attempt_rows(migrated_engine, import_id)) == 1


# ---- malformed tool calls ---------------------------------------------------------------------

MALFORMED = {
    "unknown tool": lambda a, i: ("drop_table", {"alert_id": a}),
    "not JSON": lambda a, i: ("get_import_incident", '{"alert_id": ' + str(a)),
    "JSON not an object": lambda a, i: ("get_import_incident", "[1, 2]"),
    "missing argument": lambda a, i: ("mark_needs_attention", {"alert_id": a}),
    "extra argument": lambda a, i: ("get_import_incident", {"alert_id": a, "import_id": i}),
    "id as string": lambda a, i: ("get_import_incident", {"alert_id": str(a)}),
    "id as float": lambda a, i: ("retry_failed_import", {"import_id": float(i)}),
    "id as boolean": lambda a, i: ("resolve_alert", {"alert_id": True}),
    "id as null": lambda a, i: ("get_import_attempts", {"import_id": None}),
    "reason not a string": lambda a, i: ("mark_needs_attention", {"alert_id": a, "reason": 7}),
}


@pytest.mark.parametrize("case", list(MALFORMED))
def test_a_malformed_call_runs_no_tool_and_counts_toward_the_limit(
    client, migrated_engine, ns, spy_tools, case
):
    body = injected(client, ns.name())
    alert_id, import_id = ids(body)
    name, raw_input = MALFORMED[case](alert_id, import_id)
    model = fake.FakeAnthropic(
        [
            fake.raw(name, raw_input),
            # Would be executed if the malformed call did not count (limit 1).
            fake.call("retry_failed_import", import_id=import_id),
        ]
    )

    summary = run_claimed(model, alert_id, import_id, max_tool_calls=1)

    assert spy_tools == []  # no tool function ran for the model
    assert summary.tool_calls == 1
    assert (summary.outcome, summary.close_reason) == ("NEEDS_ATTENTION", llm.REASON_LIMITS)
    [error] = model.tool_results()
    assert error["is_error"] is True
    assert json.loads(error["content"])["error"].startswith("refused: ")
    assert len(attempt_rows(migrated_engine, import_id)) == 1
    refusals = next(
        row for row in action_rows(migrated_engine, alert_id) if row["action"] == "TOOL_CALL"
    )
    assert refusals["reason_summary"].startswith("refused by the worker: ")
    assert refusals["tool_name"] == (None if case == "unknown tool" else name)


def test_a_malformed_call_lets_the_model_try_again(client, migrated_engine, ns):
    body = injected(client, ns.name())
    alert_id, import_id = ids(body)
    script = [
        fake.raw("get_import_incident", {"alert_id": str(alert_id)}),
        fake.call("get_import_incident", alert_id=alert_id),
        fake.call("retry_failed_import", import_id=import_id),
        fake.call("resolve_alert", alert_id=alert_id),
    ]

    summary = run_claimed(fake.FakeAnthropic(script), alert_id, import_id)

    assert (summary.outcome, summary.tool_calls) == ("RESOLVED", 4)
    assert import_row(migrated_engine, import_id)["status"] == "COMPLETED"
