"""The `TOOL_CALL` audit rows of the six tools (#10; spec section 4 F5).

One row per call whose target has an alert, refusals included; none for an
unknown id or an import with no alert (`agent_actions.alert_id` is required).
"""

import json

from app.services import agent_tools
from app.services.agent_tools import (
    get_import_attempts,
    get_import_diagnostics,
    get_import_incident,
    mark_needs_attention,
    resolve_alert,
    retry_failed_import,
)
from tests.integration.tooling import (
    action_count,
    action_rows,
    force_upsert_error,
    injected,
    operational_error,
    upload,
)


def assert_audit_row(action: dict, tool: str, alert_id: int, import_id: int, outcome: str) -> None:
    assert (action["action"], action["tool_name"], action["alert_id"]) == (
        "TOOL_CALL",
        tool,
        alert_id,
    )
    result = action["result"]
    assert set(result) <= agent_tools.ALLOWED_KEYS
    assert len(json.dumps(result).encode()) <= agent_tools.MAX_AUDIT_RESULT_BYTES
    assert (result["outcome"], result["alert_id"], result["import_id"]) == (
        outcome,
        alert_id,
        import_id,
    )
    assert ("refused_reason" in result) == (outcome != "DONE")


def test_every_call_on_an_alerted_import_writes_one_row(client, migrated_engine, ns):
    body = injected(client, ns.name())
    alert_id, import_id = body["alert"]["id"], body["id"]

    calls = [
        ("get_import_incident", get_import_incident(alert_id)),
        ("get_import_attempts", get_import_attempts(import_id)),
        ("get_import_diagnostics", get_import_diagnostics(import_id)),
        ("mark_needs_attention", mark_needs_attention(alert_id, "needs a look")),  # OPEN: refused
        ("retry_failed_import", retry_failed_import(import_id)),
        ("retry_failed_import", retry_failed_import(import_id)),  # refused
        ("resolve_alert", resolve_alert(alert_id)),
    ]

    actions = action_rows(migrated_engine, alert_id)
    assert len(actions) == len(calls)
    for (tool, result), action in zip(calls, actions, strict=True):
        assert_audit_row(action, tool, alert_id, import_id, result["outcome"])
        if "refused_reason" in result:
            assert action["result"]["refused_reason"] == result["refused_reason"]
    assert [r["outcome"] for _, r in calls] == [
        "DONE",
        "DONE",
        "DONE",
        "REFUSED",
        "DONE",
        "REFUSED",
        "DONE",
    ]
    assert actions[3]["reason_summary"] is None  # a refused mark stores nothing

    # The rows are the import's timeline, oldest first.
    timeline = client.get(f"/api/imports/{import_id}").json()["agent_actions"]
    assert [(a["action"], a["tool_name"]) for a in timeline] == [
        ("TOOL_CALL", tool) for tool, _ in calls
    ]
    assert [a["result"] for a in timeline] == [a["result"] for a in actions]


def test_a_retry_whose_attempt_2_fails_writes_a_done_row(client, migrated_engine, ns, monkeypatch):
    body = injected(client, ns.name())
    force_upsert_error(monkeypatch, operational_error())

    retry_failed_import(body["id"])

    [action] = action_rows(migrated_engine, body["alert"]["id"])
    assert_audit_row(action, "retry_failed_import", body["alert"]["id"], body["id"], "DONE")
    assert (action["result"]["import_status"], action["result"]["attempt_count"]) == ("FAILED", 2)


def test_no_row_without_an_alert(client, migrated_engine, ns):
    plain = upload(client, ns.name())  # first-attempt COMPLETED: no alert
    assert plain["alert"] is None
    before = action_count(migrated_engine)

    results = [
        get_import_attempts(plain["id"]),
        get_import_diagnostics(plain["id"]),
        retry_failed_import(plain["id"]),
    ]
    unknown = 2**63 - 1
    results += [
        get_import_incident(unknown),
        get_import_attempts(unknown),
        get_import_diagnostics(unknown),
        retry_failed_import(unknown),
        mark_needs_attention(unknown, "reason"),
        resolve_alert(unknown),
    ]

    assert [r["outcome"] for r in results] == ["DONE", "DONE", "REFUSED"] + ["NOT_FOUND"] * 6
    assert action_count(migrated_engine) == before
