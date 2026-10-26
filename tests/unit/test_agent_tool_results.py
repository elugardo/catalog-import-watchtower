"""The agent tool result builders and the redaction contract, with no database (#10).

The builders get fixed rows, model instances built in memory, whose catalog
fields are canary strings. Every key of every result, at any depth, must be in
the allowed-key list of `_docs/api.md` -> *Redaction contract*, and no canary
may appear in any serialised result.
"""

import io
import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.models import Alert, Import, ImportAttempt
from app.oncall import cli
from app.services import agent_tools as tools

CANARY = "CANARY-UNIT-7f3a9c"

# `_docs/api.md` -> *Redaction contract* is the source: the test image ships that
# one file (`Dockerfile.test.dockerignore`), so a change to either side alone fails.
API_MD = Path(__file__).resolve().parents[2] / "_docs" / "api.md"


def redaction_contract_list(label: str) -> list[str]:
    """The backticked values of one bold paragraph of *Redaction contract*, in order."""
    text = API_MD.read_text(encoding="utf-8")
    section = text.split("## Redaction contract", 1)[1].split("\n## ", 1)[0]
    match = re.search(re.escape(label) + r"(.*?)\n\s*\n", section, re.DOTALL)
    assert match, f"{label} not found in _docs/api.md -> Redaction contract"
    listed = re.sub(r"\([^)]*\)", "", match.group(1))  # a parenthetical is a note, not the list
    return re.findall(r"`([a-z_]+)`", listed)


API_MD_ALLOWED_KEYS = redaction_contract_list("**Allowed keys**")
API_MD_REFUSED_REASONS = redaction_contract_list("**`refused_reason` values**")


def keys_at_any_depth(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = set(value)
        for item in value.values():
            found |= keys_at_any_depth(item)
        return found
    if isinstance(value, list):
        return set().union(*(keys_at_any_depth(item) for item in value)) if value else set()
    return set()


def test_the_allowed_keys_are_the_api_md_list():
    assert len(API_MD_ALLOWED_KEYS) == len(set(API_MD_ALLOWED_KEYS)), API_MD_ALLOWED_KEYS
    assert tools.ALLOWED_KEYS == set(API_MD_ALLOWED_KEYS)


def test_the_refused_reasons_are_the_api_md_list():
    assert set(tools.REFUSED_REASONS) == set(API_MD_REFUSED_REASONS)
    assert len(set(tools.REFUSED_REASONS)) == len(tools.REFUSED_REASONS)
    assert len(API_MD_REFUSED_REASONS) == len(set(API_MD_REFUSED_REASONS))


# ---- fixed rows ----------------------------------------------------------------------------

CREATED = datetime(2026, 10, 25, 9, 30, 0, 123456, tzinfo=timezone(timedelta(hours=2)))


def canary_import(**overrides: Any) -> Import:
    values: dict[str, Any] = {
        "id": 41,
        "vendor_id": 5,
        "filename": f"{CANARY}-file.csv",
        "csv_bytes": f"sku,name,price,quantity\n{CANARY},{CANARY},1.00,1\n".encode(),
        "sha256": "0" * 64,
        "row_count": 2,
        "product_count": None,
        "status": "FAILED",
        "failure_code": "VALIDATION_ERROR",
        "validation_errors_json": [
            {"line": 2, "column": "price", "message": f"must be a plain amount, got '{CANARY}'"},
            {"line": 3, "column": "sku", "message": f"duplicate SKU '{CANARY}'"},
            {"line": 2, "column": "price", "message": "must not be blank"},
            # Not a validator column: dropped, never echoed.
            {"line": 1, "column": CANARY, "message": CANARY},
        ],
        "validation_error_count": 4,
        "inject_transient_failure": False,
        "created_at": CREATED,
        "completed_at": None,
    }
    values.update(overrides)
    return Import(**values)


def canary_attempts() -> list[ImportAttempt]:
    # Deliberately out of order; the builder sorts by number.
    return [
        ImportAttempt(
            id=9,
            import_id=41,
            attempt_number=2,
            status="FAILED",
            error_code="TRANSIENT_STORAGE_TIMEOUT",
            trace_id=CANARY,  # not 32 hex characters: dropped
            started_at=CREATED + timedelta(minutes=1),
            finished_at=CREATED + timedelta(minutes=2),
        ),
        ImportAttempt(
            id=8,
            import_id=41,
            attempt_number=1,
            status="FAILED",
            error_code="TRANSIENT_STORAGE_TIMEOUT",
            trace_id="ab" * 16,
            started_at=CREATED,
            finished_at=None,
        ),
    ]


def canary_alert() -> Alert:
    return Alert(id=3, import_id=41, status="IN_PROGRESS", reason=CANARY)


def every_result() -> list[dict[str, Any]]:
    record, attempts, alert = canary_import(), canary_attempts(), canary_alert()
    incident = tools.incident_payload(record, attempts, alert)
    built = [
        tools.done(incident),
        tools.done(tools.incident_payload(record, attempts, None)),
        tools.done(tools.attempts_payload(record, attempts)),
        tools.done(tools.diagnostics_payload(record, attempts)),
        tools.done(tools.diagnostics_payload(record, [])),
        tools.not_found("alert_id", 2**70),
        tools.not_found("import_id", CANARY),
    ]
    built += [tools.refused(reason, incident) for reason in tools.REFUSED_REASONS]
    built += [tools.audit_result(result, alert_id=3, import_id=41) for result in list(built)]
    return built


# ---- the contract ----------------------------------------------------------------------------


def test_every_key_of_every_result_is_allowed():
    for result in every_result():
        assert keys_at_any_depth(result) <= tools.ALLOWED_KEYS, result


def test_no_catalog_content_in_any_result():
    for result in every_result():
        serialised = json.dumps(result)  # also proves the result is JSON-serialisable
        assert CANARY not in serialised, serialised


def test_the_incident_keys_and_values():
    incident = tools.incident_payload(canary_import(), canary_attempts(), canary_alert())

    assert list(incident) == list(tools.INCIDENT_KEYS)
    assert (incident["alert_id"], incident["alert_status"]) == (3, "IN_PROGRESS")
    assert (incident["import_id"], incident["import_status"]) == (41, "FAILED")
    assert incident["validation_error_columns"] == ["price", "sku"]
    assert incident["attempt_count"] == 2
    assert [a["number"] for a in incident["attempts"]] == [1, 2]
    assert all(list(a) == list(tools.ATTEMPT_KEYS) for a in incident["attempts"])
    assert [a["trace_id"] for a in incident["attempts"]] == ["ab" * 16, None]
    assert incident["created_at"] == "2026-10-25T07:30:00.123456Z"
    assert incident["attempts"][0]["finished_at"] is None
    assert incident["completed_at"] is None


def test_an_import_with_no_errors_has_no_columns():
    record = canary_import(validation_errors_json=[], validation_error_count=0)
    assert tools.incident_payload(record, [], None)["validation_error_columns"] == []


def test_the_attempts_and_diagnostics_keys():
    record, attempts = canary_import(), canary_attempts()

    assert list(tools.attempts_payload(record, attempts)) == list(tools.ATTEMPTS_KEYS)
    diagnostics = tools.diagnostics_payload(record, attempts)
    assert list(diagnostics) == list(tools.DIAGNOSTICS_KEYS)
    # The latest attempt (2) has no usable trace id, so there is no trace query.
    assert diagnostics["diagnostics"] == {
        "log_query": "PLACEHOLDER log query: import_id=41",
        "trace_query": None,
    }

    attempts[0].trace_id = "cd" * 16
    assert tools.diagnostics_payload(record, attempts)["diagnostics"]["trace_query"] == (
        "PLACEHOLDER trace query: trace_id=" + "cd" * 16
    )


def test_timestamps_are_utc_with_z():
    assert tools.timestamp(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)) == "2026-01-02T03:04:05Z"
    assert tools.timestamp(None) is None


def test_the_outcome_keys():
    incident = tools.incident_payload(canary_import(), [], None)

    assert tools.done(incident)["outcome"] == "DONE"
    assert "refused_reason" not in tools.done(incident)
    refusal = tools.refused("not_transient", incident)
    assert (refusal["outcome"], refusal["refused_reason"]) == ("REFUSED", "not_transient")
    assert tools.not_found("alert_id", 0) == {
        "outcome": "NOT_FOUND",
        "refused_reason": "not_found",
        "alert_id": 0,
    }
    with pytest.raises(AssertionError):
        tools.refused("free text", incident)


def test_the_audit_result_is_small_and_carries_the_ids():
    incident = tools.incident_payload(canary_import(), canary_attempts(), canary_alert())

    summary = tools.audit_result(tools.refused("not_transient", incident), alert_id=3, import_id=41)

    assert summary == {
        "outcome": "REFUSED",
        "refused_reason": "not_transient",
        "alert_id": 3,
        "import_id": 41,
        "alert_status": "IN_PROGRESS",
        "import_status": "FAILED",
        "failure_code": "VALIDATION_ERROR",
        "attempt_count": 2,
    }
    assert len(json.dumps(summary).encode()) <= tools.MAX_AUDIT_RESULT_BYTES


@pytest.mark.parametrize("value", [0, -1, 2**63, 2**80, True, "5", None, 1.0], ids=repr)
def test_values_that_are_not_row_ids(value):
    from app.services.alerts import is_row_id

    assert not is_row_id(value)


def test_row_id_bounds():
    from app.services.alerts import is_row_id

    assert is_row_id(1) and is_row_id(2**63 - 1)


# ---- CLI usage, no database --------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["no_such_tool", "1"],
        ["get_import_incident"],
        ["get_import_incident", "1", "2"],
        ["retry_failed_import", "1", "2"],
        ["mark_needs_attention", "1"],
        ["mark_needs_attention", "1", "a", "b"],
        ["resolve_alert", "abc"],
        ["get_import_attempts", "1.5"],
        ["get_import_attempts", "+1"],
        ["get_import_attempts", "9" * 5000],
    ],
    ids=lambda argv: " ".join(argv)[:40] or "no tool",
)
def test_usage_errors_exit_2_and_list_the_tools(argv, monkeypatch):
    def boom():
        raise AssertionError("a usage error must not touch the database")

    import app.db

    monkeypatch.setattr(app.db, "get_engine", boom)
    stdout, stderr = io.StringIO(), io.StringIO()

    assert cli.run(argv, stdout, stderr) == cli.EXIT_USAGE

    assert stdout.getvalue() == ""
    for name in tools.TOOL_NAMES:
        assert name in stderr.getvalue()
    assert "abc" not in stderr.getvalue()  # the value is never echoed


def test_the_cli_offers_exactly_the_six_tools_and_no_attempt_number():
    assert tuple(cli.ARGUMENTS) == tools.TOOL_NAMES == tuple(tools.TOOLS)
    for name, arguments in cli.ARGUMENTS.items():
        assert set(arguments) <= {"alert_id", "import_id", "reason"}, name
