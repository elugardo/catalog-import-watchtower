"""The durable user-impact alert (`_docs/operations.md` -> *Alerting*, layer 1).

Only create-or-update lives here: the worker's claim, the stale-claim reset and
every status change after `OPEN` are CIW-08.1 (#10).

- `record_failure_alert` is called inside the transaction that sets an import
  `FAILED` (the importer and the startup sweep), so a `FAILED` import never
  exists without its alert.
- A later failure of the same import updates that one row: `reason` and
  `updated_at` change, `status`, `claimed_at` and `created_at` do not, because
  the worker owns the status once the alert exists.
- The `reason` is one of five fixed, content-free strings built below. It never
  quotes a CSV cell, a vendor or product name, a filename, an exception message
  or the raised exception's type (the fixed word `OperationalError` in
  `operational_reason` names the class matched, not `type(exc)`), since it
  reaches the UI, the API and the LLM prompt.
"""

from collections.abc import Iterable

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Alert

MAX_REASON_LENGTH = 200

SWEEP_REASON = "INTERNAL_ERROR (found PROCESSING at startup)"


def validation_reason(attempt_number: int, error_count: int) -> str:
    noun = "validation error" if error_count == 1 else "validation errors"
    return _capped(f"VALIDATION_ERROR on attempt {attempt_number}: {error_count} {noun}")


def injected_reason(attempt_number: int) -> str:
    return _capped(f"TRANSIENT_STORAGE_TIMEOUT on attempt {attempt_number} (synthetic demo fault)")


def operational_reason(attempt_number: int) -> str:
    return _capped(
        f"TRANSIENT_STORAGE_TIMEOUT on attempt {attempt_number} (database OperationalError)"
    )


def internal_reason(attempt_number: int) -> str:
    return _capped(f"INTERNAL_ERROR on attempt {attempt_number} (unexpected error)")


def _capped(reason: str) -> str:
    return reason[:MAX_REASON_LENGTH]


def record_failure_alert(session: Session, import_id: int, reason: str) -> int:
    """Create the import's `OPEN` alert, or update the one it has; returns the alert id."""
    ((alert_id, _),) = record_failure_alerts(session, [(import_id, reason)])
    return alert_id


def record_failure_alerts(
    session: Session, failures: Iterable[tuple[int, str]]
) -> list[tuple[int, int]]:
    """`record_failure_alert` for many imports in one statement (the startup sweep).

    Returns `(alert_id, import_id)` pairs.

    One `INSERT … ON CONFLICT (import_id) DO UPDATE`, so two writers on the
    same import never race a read against an insert: the second waits on the
    unique index and then updates. A new row takes `created_at` = `updated_at`
    from the column defaults. The update sets `updated_at` itself (a Core
    upsert does not fire the model's `onupdate`) from `clock_timestamp()`, which
    is later than the existing row's `created_at` even when this transaction
    began before that row was committed.
    """
    rows = [
        {"import_id": import_id, "status": "OPEN", "reason": _capped(reason)}
        for import_id, reason in failures
    ]
    if not rows:
        return []
    statement = insert(Alert).values(rows)
    statement = statement.on_conflict_do_update(
        index_elements=[Alert.import_id],
        set_={"reason": statement.excluded.reason, "updated_at": func.clock_timestamp()},
    ).returning(Alert.id, Alert.import_id)
    return [(row.id, row.import_id) for row in session.execute(statement)]
