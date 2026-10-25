"""No catalog content in any log line when a request or a statement fails (issue #40).

The app runs under a real uvicorn server in a thread, because the leak this
guards against is uvicorn's own `Exception in ASGI application` traceback:
`TestClient` never logs it. The database errors are real PostgreSQL errors,
not monkeypatches: a `BEFORE INSERT` trigger on `products` whose message
quotes `NEW.sku` and `NEW.name`, or a partial unique index whose violation's
`DETAIL` line quotes the key. The double failure of #7 adds a trigger on
`alerts`, so the failure write fails too and the request ends in a 500.
Every trigger, function and index is dropped afterwards, and each one only
fires for the canary values, so nothing else using the database notices.

"All log output" is every record that reaches the root logger at DEBUG
(formatted with its traceback, if any) plus everything written to stdout and
stderr. `sqlalchemy.engine` stays at the WARNING level `app.services.importer`
pins it to (statement and row logging carry catalog content by design).
"""

import logging
import socket
import threading
import time
from collections.abc import Callable, Iterator

import httpx
import pytest
import uvicorn
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from tests.integration.importing import HEADER

FILENAME = "CANARYFILE40.csv"
VENDOR = "CANARYVENDOR40"
# Row 1 carries the SKU and name canaries; row 2's SKU is the canary cell value.
# Both rows share the name, so the partial unique index below rejects row 2.
CANARY_CSV = HEADER + b"CANARYSKU40,CANARYNAME40,40.40,40\nCANARYCELL40,CANARYNAME40,40.40,40\n"
FORBIDDEN = (
    "canaryvendor40",
    "canaryfile40",
    "canarysku40",
    "canaryname40",
    "canarycell40",
    "[parameters:",
    "sku_m0",
    "name_m0",
    "insert into products",
    "exception in asgi application",
    "traceback",
)
CAPTURED_LOGGERS = (
    None,  # root
    "uvicorn",
    "uvicorn.error",
    "uvicorn.access",
    "starlette",
    "fastapi",
    "sqlalchemy",
    "app",
)
INTERNAL_500 = {"code": "INTERNAL_ERROR", "message": "internal error", "details": []}

PRODUCTS_TRIGGER = """
CREATE OR REPLACE FUNCTION ciw40_products_fault() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF starts_with(NEW.sku, 'CANARY') THEN
    RAISE EXCEPTION USING MESSAGE = 'ciw40 fault on ' || NEW.sku || ' named ' || NEW.name;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER ciw40_products_fault BEFORE INSERT ON products
  FOR EACH ROW EXECUTE FUNCTION ciw40_products_fault();
"""
UNIQUE_NAME_INDEX = (
    "CREATE UNIQUE INDEX ciw40_products_name ON products (name) WHERE name = 'CANARYNAME40'"
)
ALERTS_TRIGGER = """
CREATE OR REPLACE FUNCTION ciw40_alerts_fault() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  vendor text;
BEGIN
  SELECT v.display_name INTO vendor FROM imports i JOIN vendors v ON v.id = i.vendor_id
    WHERE i.id = NEW.import_id;
  IF starts_with(vendor, 'CANARYVENDOR40') THEN
    RAISE EXCEPTION USING MESSAGE = 'ciw40 alert fault for ' || vendor;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER ciw40_alerts_fault BEFORE INSERT ON alerts
  FOR EACH ROW EXECUTE FUNCTION ciw40_alerts_fault();
"""
CLEANUP = (
    "DROP TRIGGER IF EXISTS ciw40_products_fault ON products",
    "DROP FUNCTION IF EXISTS ciw40_products_fault()",
    "DROP INDEX IF EXISTS ciw40_products_name",
    "DROP TRIGGER IF EXISTS ciw40_alerts_fault ON alerts",
    "DROP FUNCTION IF EXISTS ciw40_alerts_fault()",
)


@pytest.fixture
def db_faults(migrated_engine: Engine) -> Iterator[Callable[[str], None]]:
    """Install named faults (`products_trigger`, `unique_name`, `alerts_trigger`); all dropped after."""
    statements = {
        "products_trigger": PRODUCTS_TRIGGER,
        "unique_name": UNIQUE_NAME_INDEX,
        "alerts_trigger": ALERTS_TRIGGER,
    }

    def install(name: str) -> None:
        with migrated_engine.begin() as connection:
            connection.exec_driver_sql(statements[name])

    try:
        yield install
    finally:
        with migrated_engine.begin() as connection:
            for statement in CLEANUP:
                connection.exec_driver_sql(statement)


@pytest.fixture
def live_server(make_client, database_url, migrated_engine) -> Iterator[str]:
    """The app under a real uvicorn server on a free port; its loggers propagate to root.

    `log_config=None` keeps uvicorn from installing its own handlers, so its
    records reach pytest's capture; the lifespan is off (no startup sweep).
    """
    make_client(DATABASE_URL=database_url)  # environment and caches for the new app
    from app.main import create_app

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_config=None, lifespan="off")
    )
    thread = threading.Thread(target=server.run, name="ciw40-uvicorn", daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, "uvicorn did not start"
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=15)


@pytest.fixture
def all_output(caplog, capfd) -> Callable[[], tuple[str, list[logging.LogRecord]]]:
    """Return a reader for every log record (DEBUG and up) and stdout/stderr since the test began."""
    for name in CAPTURED_LOGGERS:
        caplog.set_level(logging.DEBUG, logger=name)
    capfd.readouterr()  # drop whatever the fixtures printed while starting the server
    formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")

    def read() -> tuple[str, list[logging.LogRecord]]:
        records = list(caplog.records)
        captured = capfd.readouterr()
        rendered = "\n".join(formatter.format(record) for record in records)
        return f"{rendered}\n{captured.out}\n{captured.err}", records

    return read


def canary_upload(base_url: str, vendor: str) -> httpx.Response:
    return httpx.post(
        f"{base_url}/api/imports",
        data={"vendor_name": vendor},
        files={"file": (FILENAME, CANARY_CSV, "text/csv")},
        timeout=60,
    )


def assert_no_canary(output: str) -> None:
    lowered = output.casefold()
    leaks = [fragment for fragment in FORBIDDEN if fragment in lowered]
    assert not leaks, f"leaked {leaks} in:\n{output}"


@pytest.mark.parametrize(
    ("fault", "error_class"),
    [
        ("products_trigger", "ProgrammingError"),  # RAISE EXCEPTION (P0001) quoting sku and name
        ("unique_name", "IntegrityError"),  # DETAIL: Key (name)=(CANARYNAME40) already exists.
    ],
)
@pytest.mark.parametrize("path", ["handled", "unhandled"])
def test_database_errors_quoting_row_values_leak_nothing(
    live_server, db_faults, all_output, ns, fault, error_class, path
):
    vendor = ns.name(VENDOR)
    db_faults(fault)
    if path == "unhandled":
        db_faults("alerts_trigger")  # #7's double failure: the failure write fails too

    response = canary_upload(live_server, vendor)
    output, records = all_output()

    if path == "handled":
        assert response.status_code == 201, response.text
        assert (response.json()["status"], response.json()["failure_code"]) == (
            "FAILED",
            "INTERNAL_ERROR",
        )
        importer_lines = [r.getMessage() for r in records if r.name == "app.services.importer"]
        assert any(f"INTERNAL_ERROR ({error_class})" in line for line in importer_lines), output
    else:
        assert response.status_code == 500
        assert response.json() == INTERNAL_500
        errors = [r for r in records if r.levelno >= logging.ERROR and r.name == "app.main"]
        assert [r.getMessage() for r in errors] == [
            "unhandled ProgrammingError in POST /api/imports"  # the alerts trigger's RAISE
        ], output
        assert errors[0].exc_info is None
    assert_no_canary(output)


def test_statement_errors_from_the_shared_engine_carry_no_parameters(make_client, database_url):
    """The engine both processes get from `app.db.get_engine` hides bound parameters.

    Division by zero: the driver message quotes nothing, so whatever appears
    in `str()` comes from SQLAlchemy's own rendering of the parameters.
    """
    make_client(DATABASE_URL=database_url)
    from app.db import get_engine

    with pytest.raises(DBAPIError) as caught, get_engine().connect() as connection:
        connection.execute(
            text("SELECT 1 / 0 WHERE CAST(:canary AS text) IS NOT NULL"),
            {"canary": "CANARYSKU40"},
        )

    message = str(caught.value)
    assert "CANARYSKU40" not in message
    assert "[parameters:" not in message
    assert "SQL parameters hidden" in message
