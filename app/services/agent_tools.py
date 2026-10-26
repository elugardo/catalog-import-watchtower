"""The six allowlisted on-call tools (spec section 4 F5, `_docs/team/oncall-agent.md`).

The guards live here, not in the callers: the LLM worker (#11) and the
maintenance CLI (`python -m app.oncall tools …`) call these same functions.

**One result shape.** Every tool returns a JSON-serialisable dict with
`outcome`: `DONE` (the tool did what it does; a read tool found its row),
`REFUSED` (a guard failed and nothing changed) or `NOT_FOUND` (the id names no
row). `REFUSED` and `NOT_FOUND` also carry `refused_reason`, one of
`REFUSED_REASONS`. A refusal returns the current state (the incident keys),
read after the lock. A tool raises only on an unexpected error, such as the
database being unreachable, and then writes no audit row. Its own
transaction rolls back; the one exception is a retry that loses the database
after attempt 2 was committed `RUNNING`: that is the crash state of
`_docs/architecture.md` step 5, which the next startup sweep fails.

**Redaction.** Results carry ids, statuses, codes, counts, timestamps and
validation column names from a fixed set, never a CSV value, a vendor or
product name, a SKU, a filename or a validation message. Every key is in
`ALLOWED_KEYS`, which is the list of `_docs/api.md` -> *Redaction contract*.

**Audit.** Every call whose target has an alert (the alert itself, or the
import's alert for the three import-keyed tools) writes exactly one
`TOOL_CALL` row in `agent_actions`, refusals included. A call on an unknown
id, or on an import with no alert, writes none (`agent_actions.alert_id` is
required). The two alert tools commit their status change and their row in
one transaction.
"""

import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import telemetry
from app.db import get_sessionmaker
from app.models import AgentAction, Alert, Import, ImportAttempt
from app.services import alerts, importer

DONE = "DONE"
REFUSED = "REFUSED"
NOT_FOUND = "NOT_FOUND"

# The closed list of `refused_reason` values (`_docs/api.md` -> *Redaction contract*).
REASON_NOT_FOUND = "not_found"
REASON_IMPORT_NOT_FAILED = "import_not_failed"
REASON_NOT_TRANSIENT = "not_transient"
REASON_RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"
REASON_ALERT_NOT_IN_PROGRESS = "alert_not_in_progress"
REASON_IMPORT_NOT_COMPLETED = "import_not_completed"
REASON_ALREADY_RESOLVED = "already_resolved"
REASON_EMPTY_REASON = "empty_reason"
REASON_ALERT_CHANGED = "alert_changed_concurrently"
REFUSED_REASONS = (
    REASON_NOT_FOUND,
    REASON_IMPORT_NOT_FAILED,
    REASON_NOT_TRANSIENT,
    REASON_RETRY_BUDGET_EXHAUSTED,
    REASON_ALERT_NOT_IN_PROGRESS,
    REASON_IMPORT_NOT_COMPLETED,
    REASON_ALREADY_RESOLVED,
    REASON_EMPTY_REASON,
    REASON_ALERT_CHANGED,
)

ATTEMPT_KEYS = ("number", "status", "error_code", "trace_id", "started_at", "finished_at")
INCIDENT_KEYS = (
    "alert_id",
    "alert_status",
    "import_id",
    "import_status",
    "failure_code",
    "attempt_count",
    "attempts",
    "row_count",
    "validation_error_count",
    "validation_error_columns",
    "created_at",
    "completed_at",
)
ATTEMPTS_KEYS = ("import_id", "attempt_count", "attempts")
DIAGNOSTICS_KEYS = (
    "import_id",
    "diagnostics",
    "attempt_count",
    "row_count",
    "validation_error_count",
)
DIAGNOSTICS_INNER_KEYS = ("log_query", "trace_query")
OUTCOME_KEYS = ("outcome", "refused_reason")
ALLOWED_KEYS = frozenset(
    INCIDENT_KEYS + ATTEMPT_KEYS + DIAGNOSTICS_KEYS + DIAGNOSTICS_INNER_KEYS + OUTCOME_KEYS
)

# The `column` values the validator writes; anything else is dropped, never echoed.
VALIDATION_COLUMNS = frozenset({"sku", "name", "price", "quantity", "header", "row", "file"})

# The audit row's `result`: the call's ids, its outcome and the state that matters.
AUDIT_KEYS = (
    "outcome",
    "refused_reason",
    "alert_id",
    "import_id",
    "alert_status",
    "import_status",
    "failure_code",
    "attempt_count",
)
MAX_AUDIT_RESULT_BYTES = 2048

RETRYABLE_CODE = "TRANSIENT_STORAGE_TIMEOUT"
RETRY_ATTEMPT_NUMBER = 2

# Placeholders until the observability queries land (#13). They contain fixed
# text and the two ids only.
LOG_QUERY_PLACEHOLDER = "PLACEHOLDER log query: import_id={import_id}"
TRACE_QUERY_PLACEHOLDER = "PLACEHOLDER trace query: trace_id={trace_id}"
_TRACE_ID_RE = re.compile(r"[0-9a-f]{32}")

TOOL_NAMES = (
    "get_import_incident",
    "get_import_attempts",
    "get_import_diagnostics",
    "retry_failed_import",
    "mark_needs_attention",
    "resolve_alert",
)


# ---- the result builders (pure; `tests/unit/test_agent_tool_results.py`) -----------------


class ImportFacts(Protocol):
    id: int
    status: str
    failure_code: str | None
    row_count: int
    validation_error_count: int
    validation_errors_json: list[dict[str, Any]]
    created_at: datetime
    completed_at: datetime | None


class AttemptFacts(Protocol):
    attempt_number: int
    status: str
    error_code: str | None
    trace_id: str | None
    started_at: datetime
    finished_at: datetime | None


class AlertFacts(Protocol):
    id: int
    status: str


def timestamp(value: datetime | None) -> str | None:
    """ISO-8601 UTC with `Z`, as the API serialises it."""
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _trace_id(value: str | None) -> str | None:
    """A trace id only when it is 32 lowercase hex characters; anything else is dropped."""
    return value if value is not None and _TRACE_ID_RE.fullmatch(value) else None


def attempt_payload(attempt: AttemptFacts) -> dict[str, Any]:
    return {
        "number": attempt.attempt_number,
        "status": attempt.status,
        "error_code": attempt.error_code,
        "trace_id": _trace_id(attempt.trace_id),
        "started_at": timestamp(attempt.started_at),
        "finished_at": timestamp(attempt.finished_at),
    }


def _attempts(attempts: Sequence[AttemptFacts]) -> list[dict[str, Any]]:
    return [attempt_payload(a) for a in sorted(attempts, key=lambda a: a.attempt_number)]


def validation_error_columns(errors: Sequence[dict[str, Any]]) -> list[str]:
    """Sorted distinct `column` values of the stored errors, from the fixed set only."""
    return sorted({e.get("column") for e in errors} & VALIDATION_COLUMNS)


def incident_payload(
    record: ImportFacts, attempts: Sequence[AttemptFacts], alert: AlertFacts | None
) -> dict[str, Any]:
    """The incident keys; `alert_id` / `alert_status` are null for an import with no alert."""
    return {
        "alert_id": alert.id if alert is not None else None,
        "alert_status": alert.status if alert is not None else None,
        "import_id": record.id,
        "import_status": record.status,
        "failure_code": record.failure_code,
        "attempt_count": len(attempts),
        "attempts": _attempts(attempts),
        "row_count": record.row_count,
        "validation_error_count": record.validation_error_count,
        "validation_error_columns": validation_error_columns(record.validation_errors_json),
        "created_at": timestamp(record.created_at),
        "completed_at": timestamp(record.completed_at),
    }


def attempts_payload(record: ImportFacts, attempts: Sequence[AttemptFacts]) -> dict[str, Any]:
    return {
        "import_id": record.id,
        "attempt_count": len(attempts),
        "attempts": _attempts(attempts),
    }


def diagnostics_payload(record: ImportFacts, attempts: Sequence[AttemptFacts]) -> dict[str, Any]:
    """Placeholder query strings until #13; `trace_query` is null without a trace id."""
    latest = max(attempts, key=lambda a: a.attempt_number, default=None)
    trace_id = _trace_id(latest.trace_id) if latest is not None else None
    return {
        "import_id": record.id,
        "diagnostics": {
            "log_query": LOG_QUERY_PLACEHOLDER.format(import_id=record.id),
            "trace_query": (
                TRACE_QUERY_PLACEHOLDER.format(trace_id=trace_id) if trace_id is not None else None
            ),
        },
        "attempt_count": len(attempts),
        "row_count": record.row_count,
        "validation_error_count": record.validation_error_count,
    }


def done(payload: dict[str, Any]) -> dict[str, Any]:
    return {"outcome": DONE, **payload}


def refused(reason: str, state: dict[str, Any]) -> dict[str, Any]:
    assert reason in REFUSED_REASONS, reason
    return {"outcome": REFUSED, "refused_reason": reason, **state}


def not_found(id_key: str, value: object) -> dict[str, Any]:
    """The id is echoed only when it is an int; it names no row either way."""
    echoed = value if isinstance(value, int) and not isinstance(value, bool) else None
    return {"outcome": NOT_FOUND, "refused_reason": REASON_NOT_FOUND, id_key: echoed}


def audit_result(result: dict[str, Any], *, alert_id: int, import_id: int) -> dict[str, Any]:
    """The `agent_actions.result` of a call: its ids, outcome, reason and a little state."""
    summary = {key: result[key] for key in AUDIT_KEYS if key in result}
    summary["alert_id"], summary["import_id"] = alert_id, import_id
    if len(json.dumps(summary).encode()) > MAX_AUDIT_RESULT_BYTES:  # cannot happen; stay bounded
        summary = {key: summary[key] for key in AUDIT_KEYS[:4] if key in summary}
    return summary


# ---- database access ---------------------------------------------------------------------


def _session() -> Session:
    return get_sessionmaker()()


_IMPORT_FACTS = (
    Import.id,
    Import.status,
    Import.failure_code,
    Import.row_count,
    Import.validation_error_count,
    Import.validation_errors_json,
    Import.created_at,
    Import.completed_at,
)


def _load(session: Session, import_id: int) -> tuple[Any, list[ImportAttempt], Any] | None:
    """The import's facts (never `csv_bytes`, the filename or the vendor), attempts and alert."""
    record = session.execute(select(*_IMPORT_FACTS).where(Import.id == import_id)).first()
    if record is None:
        return None
    attempts = list(
        session.execute(
            select(ImportAttempt)
            .where(ImportAttempt.import_id == import_id)
            .order_by(ImportAttempt.attempt_number)
        ).scalars()
    )
    alert = session.execute(
        select(Alert.id, Alert.status).where(Alert.import_id == import_id)
    ).first()
    return record, attempts, alert


def _incident(session: Session, import_id: int) -> dict[str, Any]:
    loaded = _load(session, import_id)
    assert loaded is not None  # imports are never deleted by the app
    return incident_payload(*loaded)


def _audit(
    session: Session,
    tool_name: str,
    result: dict[str, Any],
    *,
    alert_id: int,
    import_id: int,
    reason_summary: str | None = None,
) -> None:
    session.add(
        AgentAction(
            alert_id=alert_id,
            action="TOOL_CALL",
            tool_name=tool_name,
            reason_summary=reason_summary,
            result=audit_result(result, alert_id=alert_id, import_id=import_id),
        )
    )
    session.flush()


def _read_alert(session: Session, alert_id: int) -> Any:
    """The alert's id, status and import, or None. The alert tools compare-and-set on this status."""
    return session.execute(
        select(Alert.id, Alert.status, Alert.import_id).where(Alert.id == alert_id)
    ).first()


def _lock_import(session: Session, import_id: int) -> Any:
    """`SELECT … FOR UPDATE` on the import row: the retry's lock (architecture step 4)."""
    return session.execute(
        select(Import.id, Import.status, Import.failure_code)
        .where(Import.id == import_id)
        .with_for_update()
    ).first()


def _transition(
    session: Session, alert_id: int, expected: str, new_status: str, **values: Any
) -> bool:
    """Compare-and-set the alert from `expected` to `new_status`; True when this call won."""
    changed = session.execute(
        update(Alert)
        .where(Alert.id == alert_id, Alert.status == expected)
        .values(status=new_status, updated_at=func.clock_timestamp(), **values)
        .returning(Alert.id)
    ).first()
    return changed is not None


# ---- the three read tools ----------------------------------------------------------------


def get_import_incident(alert_id: int) -> dict[str, Any]:
    """The redacted incident of one alert."""
    if not alerts.is_row_id(alert_id):
        return not_found("alert_id", alert_id)
    with _session() as session, session.begin():
        alert = _read_alert(session, alert_id)
        if alert is None:
            return not_found("alert_id", alert_id)
        result = done(_incident(session, alert.import_id))
        _audit(session, "get_import_incident", result, alert_id=alert.id, import_id=alert.import_id)
    return result


def get_import_attempts(import_id: int) -> dict[str, Any]:
    """The attempts of one import, in any status, with or without an alert."""
    if not alerts.is_row_id(import_id):
        return not_found("import_id", import_id)
    with _session() as session, session.begin():
        loaded = _load(session, import_id)
        if loaded is None:
            return not_found("import_id", import_id)
        record, attempts, alert = loaded
        result = done(attempts_payload(record, attempts))
        if alert is not None:
            _audit(session, "get_import_attempts", result, alert_id=alert.id, import_id=import_id)
    return result


def get_import_diagnostics(import_id: int) -> dict[str, Any]:
    """Observability query strings for the import and its latest trace, plus its counts."""
    if not alerts.is_row_id(import_id):
        return not_found("import_id", import_id)
    with _session() as session, session.begin():
        loaded = _load(session, import_id)
        if loaded is None:
            return not_found("import_id", import_id)
        record, attempts, alert = loaded
        result = done(diagnostics_payload(record, attempts))
        if alert is not None:
            _audit(
                session, "get_import_diagnostics", result, alert_id=alert.id, import_id=import_id
            )
    return result


# ---- retry_failed_import -----------------------------------------------------------------


def _retry_refusal(status: str, failure_code: str | None, attempt_count: int) -> str | None:
    """The three retry guards, in order; None when the retry may run."""
    if status != "FAILED":
        return REASON_IMPORT_NOT_FAILED
    if failure_code != RETRYABLE_CODE:
        return REASON_NOT_TRANSIENT
    if attempt_count != 1:
        return REASON_RETRY_BUDGET_EXHAUSTED
    return None


def retry_failed_import(import_id: int) -> dict[str, Any]:
    """Re-process the saved CSV as attempt 2, once, under the import's row lock.

    The guard is read after `SELECT … FOR UPDATE`: status `FAILED`, code
    `TRANSIENT_STORAGE_TIMEOUT`, exactly one attempt. When it passes, the same
    transaction sets the import back to `PROCESSING` and inserts attempt 2 as
    `RUNNING`, and commits before processing starts, so a concurrent call
    waits on the lock, re-reads `PROCESSING` and is refused. Processing is
    `importer.process_attempt` on the stored `csv_bytes`, the same code as the
    upload's attempt 1. The alert is not touched on success; a failed
    attempt 2 updates it under the importer's rule. `DONE` reports the state
    that resulted, `FAILED` included.
    """
    if not alerts.is_row_id(import_id):
        return not_found("import_id", import_id)
    # Attempt 2's span starts once the guard passed, as a child of the current
    # span (the worker's `retry_failed_import` tool span; none from the CLI, so
    # there it is the root of its own trace). `begin_attempt` stores its trace id.
    attempt_span = None
    try:
        with _session() as session, session.begin():
            locked = _lock_import(session, import_id)
            if locked is None:
                return not_found("import_id", import_id)
            attempt_count = session.execute(
                select(func.count())
                .select_from(ImportAttempt)
                .where(ImportAttempt.import_id == import_id)
            ).scalar_one()
            reason = _retry_refusal(locked.status, locked.failure_code, attempt_count)
            if reason is not None:
                result = refused(reason, _incident(session, import_id))
                if result["alert_id"] is not None:
                    _audit(
                        session,
                        "retry_failed_import",
                        result,
                        alert_id=result["alert_id"],
                        import_id=import_id,
                    )
                return result
            attempt_span = importer.attempt_span(import_id, RETRY_ATTEMPT_NUMBER)
            with telemetry.use_span(attempt_span, end_on_exit=False):
                attempt_id = importer.begin_attempt(session, import_id, RETRY_ATTEMPT_NUMBER)
    except BaseException:
        if attempt_span is not None:
            attempt_span.end()
        raise

    with telemetry.use_span(attempt_span):
        importer.process_attempt(import_id, attempt_id, RETRY_ATTEMPT_NUMBER)

    with _session() as session, session.begin():
        result = done(_incident(session, import_id))
        if result["alert_id"] is not None:
            _audit(
                session,
                "retry_failed_import",
                result,
                alert_id=result["alert_id"],
                import_id=import_id,
            )
    return result


# ---- the two alert tools -----------------------------------------------------------------


def mark_needs_attention(alert_id: int, reason: str) -> dict[str, Any]:
    """`IN_PROGRESS -> NEEDS_ATTENTION` with a trimmed reason of at most 200 characters."""
    if not alerts.is_row_id(alert_id):
        return not_found("alert_id", alert_id)
    trimmed = reason.strip() if isinstance(reason, str) else ""
    stored = trimmed[: alerts.MAX_REASON_LENGTH].rstrip()
    with _session() as session, session.begin():
        alert = _read_alert(session, alert_id)
        if alert is None:
            return not_found("alert_id", alert_id)
        refusal: str | None = None
        if not stored:
            refusal = REASON_EMPTY_REASON
        elif alert.status != "IN_PROGRESS":
            refusal = REASON_ALERT_NOT_IN_PROGRESS
        elif not _transition(session, alert_id, alert.status, "NEEDS_ATTENTION", reason=stored):
            refusal = REASON_ALERT_NOT_IN_PROGRESS  # another caller changed it first
        state = _incident(session, alert.import_id)
        if refusal is None:
            result = done(state)
            summary: str | None = stored
        else:
            result, summary = refused(refusal, state), None
        _audit(
            session,
            "mark_needs_attention",
            result,
            alert_id=alert_id,
            import_id=alert.import_id,
            reason_summary=summary,
        )
    return result


def resolve_alert(alert_id: int) -> dict[str, Any]:
    """`OPEN`, `IN_PROGRESS` or `NEEDS_ATTENTION` -> `RESOLVED`, only when the import is `COMPLETED`."""
    if not alerts.is_row_id(alert_id):
        return not_found("alert_id", alert_id)
    with _session() as session, session.begin():
        alert = _read_alert(session, alert_id)
        if alert is None:
            return not_found("alert_id", alert_id)
        refusal: str | None = None
        if alert.status == "RESOLVED":
            refusal = REASON_ALREADY_RESOLVED
        else:
            import_status = session.execute(
                select(Import.status).where(Import.id == alert.import_id)
            ).scalar_one()
            if import_status != "COMPLETED":
                refusal = REASON_IMPORT_NOT_COMPLETED
            elif not _transition(session, alert_id, alert.status, "RESOLVED"):
                # Another caller changed it between the read and the update.
                current = session.execute(
                    select(Alert.status).where(Alert.id == alert_id)
                ).scalar_one()
                refusal = REASON_ALREADY_RESOLVED if current == "RESOLVED" else REASON_ALERT_CHANGED
        state = _incident(session, alert.import_id)
        result = done(state) if refusal is None else refused(refusal, state)
        _audit(session, "resolve_alert", result, alert_id=alert_id, import_id=alert.import_id)
    return result


TOOLS = {
    "get_import_incident": get_import_incident,
    "get_import_attempts": get_import_attempts,
    "get_import_diagnostics": get_import_diagnostics,
    "retry_failed_import": retry_failed_import,
    "mark_needs_attention": mark_needs_attention,
    "resolve_alert": resolve_alert,
}
