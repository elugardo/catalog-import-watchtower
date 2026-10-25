"""The import write path (`_docs/architecture.md` -> *Import processing*).

- `create_import` finds or creates the vendor and inserts the import as
  `PROCESSING`, each in its own committed transaction (steps 1).
- `run_attempt` inserts the attempt as `RUNNING` (own transaction), validates
  the whole file, then either records `FAILED` / `VALIDATION_ERROR` with no
  product write, or upserts every row and marks the import `COMPLETED` in one
  transaction. The synthetic failure injector raises at the start of that
  transaction, before any product statement, on attempt 1 only. Any exception
  in that transaction rolls it back: the injected fault and a real
  `OperationalError` end `FAILED` / `TRANSIENT_STORAGE_TIMEOUT`, anything else
  `FAILED` / `INTERNAL_ERROR`.
- Every `FAILED` transition writes the import's alert in the same short
  transaction (`app/services/alerts.py`); a success never touches the alert.
- `sweep_stuck_imports` is the startup crash recovery (step 5), alert included.
- `load_import_detail` is the read side of `GET /api/imports/{id}`;
  `import_summary` builds the `Import` fields it shares with `GET /api/imports`
  (`app/services/lists.py`).

Logs carry only ids, counts and codes, never catalog content (AGENTS.md ->
Rules); exceptions are logged by type, because a driver message can quote the
SQL parameters.
"""

import hashlib
import logging
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import get_sessionmaker
from app.models import AgentAction, Alert, Import, ImportAttempt, Product
from app.schemas import ImportDetailOut
from app.schemas.upload import UploadRequest
from app.services import alerts
from app.services.csv_validation import ProductRow, validate_csv
from app.services.vendors import find_or_create_vendor

log = logging.getLogger(__name__)

# SQLAlchemy logs statements with their parameters at INFO and result rows at
# DEBUG; both carry catalog content. Keep that logger quiet whatever the root
# level is (the no-catalog-in-logs rule holds with DEBUG logging on).
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

STORED_VALIDATION_ERRORS = 20


class InjectedTransientFailure(Exception):
    """The synthetic demo fault: the upload asked for a failed first attempt.

    Not a real storage outage. Raised only inside the upsert transaction, before
    any product statement, so the rollback has nothing to undo.
    """


def _session() -> Session:
    return get_sessionmaker()()


def create_import(request: UploadRequest) -> int:
    """Vendor find-or-create, then the import row as `PROCESSING`; returns its id."""
    with _session() as session:
        with session.begin():
            vendor_id = find_or_create_vendor(session, request.vendor_name).id
        with session.begin():
            record = Import(
                vendor_id=vendor_id,
                filename=request.filename,
                csv_bytes=request.data,
                sha256=hashlib.sha256(request.data).hexdigest(),
                status="PROCESSING",
                inject_transient_failure=request.inject_transient_failure,
            )
            session.add(record)
            session.flush()
            import_id = record.id
    log.info("import %d created", import_id)
    return import_id


def run_attempt(import_id: int, attempt_number: int) -> None:
    """Process one attempt of an import whose row already exists. Never raises for bad data.

    `attempt_number` is 1 from the upload; the agent's retry (CIW-08.1) passes 2.
    The injection flag is read from the persisted import row, never from a
    setting, so an injected upload affects no other import.
    """
    with _session() as session:
        with session.begin():
            attempt = ImportAttempt(
                import_id=import_id, attempt_number=attempt_number, status="RUNNING"
            )
            session.add(attempt)
            session.flush()
            attempt_id = attempt.id
            row = session.execute(
                select(Import.vendor_id, Import.csv_bytes, Import.inject_transient_failure).where(
                    Import.id == import_id
                )
            ).one()
        vendor_id, csv_bytes = row.vendor_id, row.csv_bytes
        inject = row.inject_transient_failure and attempt_number == 1

        result = validate_csv(csv_bytes)
        if result.errors:
            # Validation wins over injection: the flag is never looked at here.
            with session.begin():
                _finish(
                    session,
                    import_id,
                    attempt_id,
                    succeeded=False,
                    code="VALIDATION_ERROR",
                    import_values={
                        "row_count": result.row_count,
                        "validation_errors_json": result.errors[:STORED_VALIDATION_ERRORS],
                        "validation_error_count": result.error_count,
                    },
                )
                alert_id = alerts.record_failure_alert(
                    session,
                    import_id,
                    alerts.validation_reason(attempt_number, result.error_count),
                )
            log.info(
                "import %d attempt %d failed: VALIDATION_ERROR, %d errors",
                import_id,
                attempt_number,
                result.error_count,
            )
            _log_alert(alert_id, import_id, "VALIDATION_ERROR", attempt_number)
            return

        try:
            # One transaction: every product row and the COMPLETED transition
            # commit together, or nothing does.
            with session.begin():
                if inject:
                    raise InjectedTransientFailure
                _upsert_products(session, vendor_id, result.rows)
                _finish(
                    session,
                    import_id,
                    attempt_id,
                    succeeded=True,
                    code=None,
                    import_values={
                        "row_count": result.row_count,
                        "product_count": len(result.rows),
                        "completed_at": func.now(),
                        "validation_errors_json": [],
                        "validation_error_count": 0,
                    },
                )
        except Exception as exc:  # noqa: BLE001 - every runtime failure ends the attempt
            code, reason = _classify(exc, attempt_number)
            log.error(
                "import %d attempt %d failed: %s (%s)",
                import_id,
                attempt_number,
                code,
                type(exc).__name__,
            )
            # If this write raises too, the request answers 500 and the import
            # stays PROCESSING with no alert until the next startup sweep.
            with session.begin():
                _finish(
                    session,
                    import_id,
                    attempt_id,
                    succeeded=False,
                    code=code,
                    import_values={"row_count": result.row_count},
                )
                alert_id = alerts.record_failure_alert(session, import_id, reason)
            _log_alert(alert_id, import_id, code, attempt_number)
            return
    log.info(
        "import %d attempt %d completed: %d products",
        import_id,
        attempt_number,
        len(result.rows),
    )


def _classify(exc: Exception, attempt_number: int) -> tuple[str, str]:
    """The failure code and alert reason for an exception in the upsert transaction.

    Only the exception's class is looked at; its message is never used.
    """
    if isinstance(exc, InjectedTransientFailure):
        return "TRANSIENT_STORAGE_TIMEOUT", alerts.injected_reason(attempt_number)
    if isinstance(exc, OperationalError):
        return "TRANSIENT_STORAGE_TIMEOUT", alerts.operational_reason(attempt_number)
    return "INTERNAL_ERROR", alerts.internal_reason(attempt_number)


def _log_alert(alert_id: int, import_id: int, code: str, attempt_number: int | None) -> None:
    """The one log line per alert write: ids, the code and the attempt number only."""
    if attempt_number is None:  # the startup sweep
        log.warning("alert %d for import %d: %s (startup sweep)", alert_id, import_id, code)
        return
    log.warning(
        "alert %d for import %d: %s on attempt %d", alert_id, import_id, code, attempt_number
    )


def _upsert_products(session: Session, vendor_id: int, rows: list[ProductRow]) -> None:
    """Insert new SKUs, update existing ones unconditionally; never deletes.

    A Core upsert does not fire the model's `onupdate`, so `updated_at` is set
    here; the latest upload's spelling of `sku` wins like every other column.
    """
    statement = insert(Product).values(
        [
            {
                "vendor_id": vendor_id,
                "sku": row["sku"],
                "normalized_sku": row["normalized_sku"],
                "name": row["name"],
                "price_cents": row["price_cents"],
                "quantity": row["quantity"],
            }
            for row in rows
        ]
    )
    statement = statement.on_conflict_do_update(
        index_elements=[Product.vendor_id, Product.normalized_sku],
        set_={
            "sku": statement.excluded.sku,
            "name": statement.excluded.name,
            "price_cents": statement.excluded.price_cents,
            "quantity": statement.excluded.quantity,
            "updated_at": func.now(),
        },
    )
    session.execute(statement)


def _finish(
    session: Session,
    import_id: int,
    attempt_id: int,
    *,
    succeeded: bool,
    code: str | None,
    import_values: dict[str, Any],
) -> None:
    """Close the attempt and set the import's outcome, inside the caller's transaction."""
    session.execute(
        update(ImportAttempt)
        .where(ImportAttempt.id == attempt_id)
        .values(
            status="SUCCEEDED" if succeeded else "FAILED",
            error_code=code,
            finished_at=func.now(),
        )
    )
    outcome: dict[str, Any] = {"status": "COMPLETED", "failure_code": None}
    if not succeeded:
        outcome = {
            "status": "FAILED",
            "failure_code": code,
            "product_count": None,
            "completed_at": None,
        }
    session.execute(update(Import).where(Import.id == import_id).values(**outcome, **import_values))


def sweep_stuck_imports() -> int:
    """Startup crash recovery: every `PROCESSING` import and its `RUNNING` attempt become
    `FAILED` / `INTERNAL_ERROR`. Returns the number of imports swept. Runs in `app` only.

    Each swept import gets its alert in the same transaction, with the sweep
    reason; an import that already has one (a crashed attempt 2) keeps that row
    under the update rule of `alerts.record_failure_alerts`. Only `PROCESSING`
    imports are selected, so a `FAILED` import left without an alert by an
    earlier build is never backfilled.
    """
    with _session() as session, session.begin():
        stuck = select(Import.id).where(Import.status == "PROCESSING")
        session.execute(
            update(ImportAttempt)
            .where(ImportAttempt.status == "RUNNING", ImportAttempt.import_id.in_(stuck))
            .values(status="FAILED", error_code="INTERNAL_ERROR", finished_at=func.now())
        )
        swept = list(
            session.execute(
                update(Import)
                .where(Import.status == "PROCESSING")
                .values(
                    status="FAILED",
                    failure_code="INTERNAL_ERROR",
                    product_count=None,
                    completed_at=None,
                )
                .returning(Import.id)
            ).scalars()
        )
        written = alerts.record_failure_alerts(
            session, [(import_id, alerts.SWEEP_REASON) for import_id in sorted(swept)]
        )
    if swept:
        log.warning("startup sweep marked %d stuck imports FAILED / INTERNAL_ERROR", len(swept))
        for alert_id, import_id in written:
            _log_alert(alert_id, import_id, "INTERNAL_ERROR", None)
    return len(swept)


def load_import_detail(import_id: int) -> ImportDetailOut | None:
    """The import detail of `openapi.yaml` -> `ImportDetail`, or None when there is no such import."""
    with _session() as session:
        record = session.get(Import, import_id)
        if record is None:
            return None
        alert = session.execute(
            select(Alert).where(Alert.import_id == import_id)
        ).scalar_one_or_none()
        actions: list[AgentAction] = []
        if alert is not None:
            actions = list(
                session.execute(
                    select(AgentAction)
                    .where(AgentAction.alert_id == alert.id)
                    .order_by(AgentAction.created_at, AgentAction.id)
                ).scalars()
            )
        return ImportDetailOut.model_validate(
            {
                **import_summary(record),
                "attempts": record.attempts,
                "alert": alert,
                "agent_actions": actions,
            }
        )


def import_summary(record: Import) -> dict[str, Any]:
    """The fields of `openapi.yaml` -> `Import`, shared by the detail and `GET /api/imports`.

    `attempt_count` and `recovered` are derived here on every read, never stored.
    Reads `record.vendor` and `record.attempts`, so the session must still be open.
    """
    attempt_count = len(record.attempts)
    return {
        "id": record.id,
        "vendor": record.vendor,
        "filename": record.filename,
        "sha256": record.sha256,
        "row_count": record.row_count,
        "product_count": record.product_count,
        "status": record.status,
        "failure_code": record.failure_code,
        "validation_errors": record.validation_errors_json,
        "validation_error_count": record.validation_error_count,
        "inject_transient_failure": record.inject_transient_failure,
        "attempt_count": attempt_count,
        "recovered": record.status == "COMPLETED" and attempt_count > 1,
        "created_at": record.created_at,
        "completed_at": record.completed_at,
    }
