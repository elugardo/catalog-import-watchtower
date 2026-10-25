"""Unhandled exceptions and the shared engine, without a database (issue #40).

An exception that escapes a request handler is logged once, at ERROR, by
class name, method and route template (plus the import id when the route has
one), never with its message, a traceback or SQL. The engine from
`app.db.get_engine`, which the app and the `oncall-agent` process share,
hides bound parameters.
"""

import logging
import re
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError

from app.db import get_engine

UNREACHABLE_DB = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/nothing"
APP_DIR = Path(__file__).resolve().parents[2] / "app"
INTERNAL_500 = {"code": "INTERNAL_ERROR", "message": "internal error", "details": []}


class CanaryFailure(Exception):
    pass


def _error_records(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_unhandled_exception_is_logged_by_type_method_and_route(make_client, monkeypatch, caplog):
    from app.services import importer

    def exploding_detail(import_id: int):
        raise CanaryFailure("CANARYNAME40 [parameters: {'sku_m0': 'CANARYSKU40'}]")

    monkeypatch.setattr(importer, "load_import_detail", exploding_detail)
    client = make_client(DATABASE_URL=UNREACHABLE_DB)
    caplog.set_level(logging.DEBUG)

    response = client.get("/api/imports/42")

    assert response.status_code == 500
    assert response.json() == INTERNAL_500
    [record] = _error_records(caplog)
    assert record.name == "app.main"
    assert record.getMessage() == "unhandled CanaryFailure in GET /api/imports/{id} import_id=42"
    assert record.exc_info is None
    assert record.stack_info is None
    for every in caplog.records:
        assert "CANARY" not in every.getMessage() + (every.exc_text or "")


def test_the_test_client_no_longer_sees_the_exception(make_client, monkeypatch):
    """Nothing is re-raised past the app, so the server has nothing to print a traceback for."""
    from app.routers import health as health_module

    def exploding_probe() -> bool:
        raise CanaryFailure("CANARYNAME40")

    monkeypatch.setattr(health_module, "check_database", exploding_probe)
    # The default TestClient re-raises any exception that leaves the app.
    client = TestClient(make_client(DATABASE_URL=UNREACHABLE_DB).app)

    response = client.get("/api/health")

    assert response.status_code == 500
    assert response.json() == INTERNAL_500


def test_route_without_an_import_id_logs_no_id(make_client, monkeypatch, caplog):
    from app.routers import health as health_module

    def exploding_probe() -> bool:
        raise CanaryFailure("CANARYNAME40")

    monkeypatch.setattr(health_module, "check_database", exploding_probe)
    client = make_client(DATABASE_URL=UNREACHABLE_DB)
    caplog.set_level(logging.DEBUG)

    client.get("/api/health")

    assert [r.getMessage() for r in _error_records(caplog)] == [
        "unhandled CanaryFailure in GET /api/health"
    ]


def test_the_shared_engine_hides_bound_parameters(reset_caches, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DB)
    reset_caches()
    engine = get_engine()

    assert engine.hide_parameters is True
    # The error SQLAlchemy builds for a failed statement on this engine.
    error = DBAPIError.instance(
        "INSERT INTO products (sku, name) VALUES (%(sku_m0)s, %(name_m0)s)",
        {"sku_m0": "CANARYSKU40", "name_m0": "CANARYNAME40"},
        Exception("driver error"),
        Exception,
        hide_parameters=engine.hide_parameters,
        dialect=engine.dialect,
    )
    assert "CANARY" not in str(error)
    assert "[parameters:" not in str(error)


def test_get_engine_is_the_only_engine_factory_in_the_app():
    """The app and `python -m app.oncall` both get their engine from `app.db.get_engine`."""
    callers = sorted(
        path.relative_to(APP_DIR).as_posix()
        for path in APP_DIR.rglob("*.py")
        if re.search(r"\bcreate_engine\(", path.read_text(encoding="utf-8"))
    )
    assert callers == ["db.py"]
