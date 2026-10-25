"""Helpers for the agent tool tests (#10): uploads, row reads, forced failures, threads.

The tools use the app's engine (`app.db.get_engine()`), so every test that
calls one first requests `client` (shared `db`, `ns` cleanup) or `isolated_db`
(anything that runs the sweep or touches rows it did not create).
"""

import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError

from app.db import get_sessionmaker
from app.services import agent_tools, alerts, importer
from tests.integration.importing import fixture_bytes, post_import

VALID = fixture_bytes("valid.csv")
INVALID = fixture_bytes("invalid.csv")


def upload(client, vendor: str, data: bytes = VALID, *, filename="valid.csv", inject=None) -> dict:
    response = post_import(client, vendor, data, filename=filename, inject=inject)
    assert response.status_code == 201, response.text
    return response.json()


def injected(client, vendor: str) -> dict:
    """`valid.csv` uploaded with injection: `FAILED` / `TRANSIENT_STORAGE_TIMEOUT`, alert `OPEN`."""
    body = upload(client, vendor, inject="true")
    assert (body["status"], body["failure_code"]) == ("FAILED", "TRANSIENT_STORAGE_TIMEOUT")
    return body


def rows(engine: Engine, sql: str, **params: Any) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(text(sql), params).mappings()]


def attempt_rows(engine: Engine, import_id: int) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM import_attempts WHERE import_id = :i ORDER BY attempt_number",
        i=import_id,
    )


def alert_row(engine: Engine, alert_id: int) -> dict[str, Any]:
    [row] = rows(engine, "SELECT * FROM alerts WHERE id = :a", a=alert_id)
    return row


def action_rows(engine: Engine, alert_id: int) -> list[dict[str, Any]]:
    return rows(
        engine,
        "SELECT * FROM agent_actions WHERE alert_id = :a ORDER BY created_at, id",
        a=alert_id,
    )


def action_count(engine: Engine) -> int:
    return rows(engine, "SELECT count(*) AS n FROM agent_actions")[0]["n"]


def set_alert_status(engine: Engine, alert_id: int, status: str) -> None:
    """Prepare an alert in a status (as the worker would leave it); `IN_PROGRESS` sets `claimed_at`."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE alerts SET status = :s,"
                " claimed_at = CASE WHEN :claim THEN now() ELSE claimed_at END"
                " WHERE id = :a"
            ),
            {"s": status, "claim": status == "IN_PROGRESS", "a": alert_id},
        )


def claim(alert_id: int) -> bool:
    with get_sessionmaker()() as session, session.begin():
        return alerts.claim_alert(session, alert_id)


def force_upsert_error(monkeypatch, exc: Exception) -> None:
    """Every upsert transaction raises `exc` after its product statement (rolled back)."""
    original = importer._upsert_products

    def failing(session, vendor_id, product_rows):
        original(session, vendor_id, product_rows)
        raise exc

    monkeypatch.setattr(importer, "_upsert_products", failing)


def operational_error() -> OperationalError:
    return OperationalError("UPDATE products", {}, Exception("server closed the connection"))


def force_real_operational_error(monkeypatch) -> None:
    """The upsert transaction hits a genuine driver `OperationalError` (a statement timeout)."""

    def timing_out(session, vendor_id, product_rows):
        session.execute(text("SET LOCAL statement_timeout = 1"))
        session.execute(text("SELECT pg_sleep(1)"))

    monkeypatch.setattr(importer, "_upsert_products", timing_out)


def run_concurrently(*calls: Callable[[], Any], timeout: float = 30) -> list[Any]:
    """Run each call in its own thread (and so its own session); re-raise the first error."""
    results: list[Any] = [None] * len(calls)
    errors: list[BaseException] = []

    def target(index: int, call: Callable[[], Any]) -> None:
        try:
            results[index] = call()
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=target, args=(i, c)) for i, c in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout)
        assert not thread.is_alive(), "a concurrent call did not finish"
    if errors:
        raise errors[0]
    return results


def barrier_before(monkeypatch, module: Any, name: str, parties: int) -> threading.Barrier:
    """Every caller of `module.name` waits until `parties` callers have arrived, then calls it."""
    original = getattr(module, name)
    barrier = threading.Barrier(parties, timeout=20)

    def synchronised(*args, **kwargs):
        barrier.wait()
        return original(*args, **kwargs)

    monkeypatch.setattr(module, name, synchronised)
    return barrier


def barrier_after(monkeypatch, module: Any, name: str, parties: int) -> threading.Barrier:
    """Every caller of `module.name` calls it, then waits until `parties` callers have returned."""
    original = getattr(module, name)
    barrier = threading.Barrier(parties, timeout=20)

    def synchronised(*args, **kwargs):
        value = original(*args, **kwargs)
        barrier.wait()
        return value

    monkeypatch.setattr(module, name, synchronised)
    return barrier


def hold_lock_until_contended(monkeypatch, engine: Engine, parties: int = 2) -> None:
    """Make concurrent retries really contend for the import's row lock.

    Every caller of `agent_tools._lock_import` first waits for the others to
    arrive (so all are inside the tool, each with its own session). Each one
    that comes back from it holding the lock then waits, before going on to
    commit, until every other caller has either come back too or is blocked
    on a row lock. With the lock, the others are blocked and re-read after the
    commit; without it, all of them read the same `FAILED` row.
    """
    original = agent_tools._lock_import
    arrived = threading.Barrier(parties, timeout=20)
    count = {"returned": 0}
    guard = threading.Lock()

    def contended(*args, **kwargs):
        arrived.wait()
        value = original(*args, **kwargs)
        with guard:
            count["returned"] += 1
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with guard:
                others_back = count["returned"] == parties
            if others_back or backend_pid_waiting_on_lock(engine):
                break
            time.sleep(0.02)
        return value

    monkeypatch.setattr(agent_tools, "_lock_import", contended)


class Pause:
    """Pauses the first caller of a patched function until `release()`; `wait()` until it is there."""

    def __init__(self) -> None:
        self.reached = threading.Event()
        self.go = threading.Event()
        self._used = False

    def __call__(self) -> None:
        if self._used:
            return
        self._used = True
        self.reached.set()
        assert self.go.wait(30), "the paused call was never released"

    def wait(self) -> None:
        assert self.reached.wait(30), "the call never reached the pause"

    def release(self) -> None:
        self.go.set()


@contextmanager
def paused(monkeypatch, module: Any, name: str, *, after: bool = False) -> Iterator[Pause]:
    """Pause inside `module.name`: before calling it, or with `after=True` once it returned."""
    original = getattr(module, name)
    pause = Pause()

    def pausing(*args, **kwargs):
        if not after:
            pause()
            return original(*args, **kwargs)
        value = original(*args, **kwargs)
        pause()
        return value

    monkeypatch.setattr(module, name, pausing)
    try:
        yield pause
    finally:
        pause.release()


def backend_pid_waiting_on_lock(engine: Engine) -> bool:
    """True when some other backend of this database is waiting on a row lock."""
    found = rows(
        engine,
        "SELECT count(*) AS n FROM pg_stat_activity WHERE datname = current_database()"
        " AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()",
    )
    return found[0]["n"] > 0


TOOLS = agent_tools.TOOLS
