"""The three read tools (#10; spec section 4 F5, `_docs/api.md` -> *Redaction contract*)."""

import pytest
from sqlalchemy import text

from app.services import agent_tools
from app.services.agent_tools import (
    get_import_attempts,
    get_import_diagnostics,
    get_import_incident,
)
from tests.integration.tooling import INVALID, action_count, injected, upload

ATTEMPT_KEYS = set(agent_tools.ATTEMPT_KEYS)
UNKNOWN_IDS = [0, -1, -(2**63), 2**63, 2**80, 2**63 - 1]


def api_attempts(detail: dict) -> list[dict]:
    return [{key: a[key] for key in ATTEMPT_KEYS} for a in detail["attempts"]]


def test_get_import_incident_returns_exactly_the_incident_keys(client, ns):
    body = injected(client, ns.name())

    result = get_import_incident(body["alert"]["id"])

    assert list(result) == ["outcome", *agent_tools.INCIDENT_KEYS]
    detail = client.get(f"/api/imports/{body['id']}").json()
    assert result == {
        "outcome": "DONE",
        "alert_id": detail["alert"]["id"],
        "alert_status": "OPEN",
        "import_id": detail["id"],
        "import_status": "FAILED",
        "failure_code": "TRANSIENT_STORAGE_TIMEOUT",
        "attempt_count": 1,
        "attempts": api_attempts(detail),
        "row_count": 3,
        "validation_error_count": 0,
        "validation_error_columns": [],
        "created_at": detail["created_at"],
        "completed_at": None,
    }
    assert result["created_at"].endswith("Z")
    assert result["attempts"][0]["trace_id"] is None  # #12 sets trace ids


def test_validation_error_columns_are_the_sorted_distinct_columns(client, ns):
    body = upload(client, ns.name(), INVALID, filename="invalid.csv")
    header = upload(client, ns.name("Header"), b"sku,name,price\nA-1,Lamp,1.00\n")

    result = get_import_incident(body["alert"]["id"])
    header_result = get_import_incident(header["alert"]["id"])

    expected = sorted({e["column"] for e in body["validation_errors"]})
    assert result["validation_error_columns"] == expected == ["quantity"]
    assert result["validation_error_count"] == body["validation_error_count"]
    assert header_result["validation_error_columns"] == ["header"]


def test_get_import_attempts_works_on_an_import_with_no_alert(client, migrated_engine, ns):
    body = upload(client, ns.name())  # first-attempt COMPLETED: no alert
    assert body["alert"] is None
    before = action_count(migrated_engine)

    result = get_import_attempts(body["id"])

    assert list(result) == ["outcome", *agent_tools.ATTEMPTS_KEYS]
    assert result == {
        "outcome": "DONE",
        "import_id": body["id"],
        "attempt_count": 1,
        "attempts": api_attempts(body),
    }
    assert result["attempts"][0]["status"] == "SUCCEEDED"
    assert action_count(migrated_engine) == before  # no alert, no audit row


def test_get_import_diagnostics_returns_placeholders(client, migrated_engine, ns):
    body = injected(client, ns.name())

    result = get_import_diagnostics(body["id"])

    assert list(result) == ["outcome", *agent_tools.DIAGNOSTICS_KEYS]
    assert result == {
        "outcome": "DONE",
        "import_id": body["id"],
        "diagnostics": {
            "log_query": f"PLACEHOLDER log query: import_id={body['id']}",
            "trace_query": None,
        },
        "attempt_count": 1,
        "row_count": 3,
        "validation_error_count": 0,
    }

    # Once the latest attempt has a trace id (#12), the trace query names it.
    trace_id = "0123456789abcdef0123456789abcdef"
    with migrated_engine.begin() as connection:
        connection.execute(
            text("UPDATE import_attempts SET trace_id = :t WHERE import_id = :i"),
            {"t": trace_id, "i": body["id"]},
        )
    with_trace = get_import_diagnostics(body["id"])["diagnostics"]
    assert with_trace["trace_query"] == f"PLACEHOLDER trace query: trace_id={trace_id}"


@pytest.mark.parametrize("value", UNKNOWN_IDS, ids=str)
@pytest.mark.parametrize(
    ("tool", "key"),
    [
        (get_import_incident, "alert_id"),
        (get_import_attempts, "import_id"),
        (get_import_diagnostics, "import_id"),
    ],
    ids=lambda v: getattr(v, "__name__", v),
)
def test_an_id_that_names_no_row_is_not_found(client, migrated_engine, tool, key, value):
    before = action_count(migrated_engine)

    result = tool(value)

    assert result == {"outcome": "NOT_FOUND", "refused_reason": "not_found", key: value}
    assert action_count(migrated_engine) == before
