"""Metrics, metric labels and the privacy of every exported signal (#12).

The privacy test runs the fixture sequence (valid, invalid, injected failure
plus the fake-LLM recovery of #11, and #40's double failure under a real
uvicorn server) with the in-memory exporters, the JSON formatter and the OTLP
log handler installed, then searches every span, span event, status, log
record, JSON line and metric label for the canaries.
"""

import csv
import io
import json
import socket
import threading
import time
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import uvicorn
from opentelemetry.trace import SpanKind, StatusCode

from app import telemetry
from app.services import importer
from tests.integration.importing import HEADER, fixture_bytes
from tests.integration.test_log_privacy import (  # noqa: F401 - fixtures
    CANARY_CSV,
    FILENAME,
    VENDOR,
    db_faults,
)
from tests.integration.tooling import INVALID, VALID, injected, rows, upload
from tests.oncall import fake_llm as fake
from tests.oncall.helpers import run_claimed

CANARY_VENDOR = "CANARYVENDOR12"
CANARY_FILE = "CANARYFILE12.csv"
CANARY_KEY = "sk-ant-CANARYKEY12"
CANARY_VALID = HEADER + b"CANARYSKU12,CANARYNAME12,12.12,12\n"
CANARY_INVALID = HEADER + b"CANARYSKU12B,CANARYNAME12B,CANARYCELL12,12\n"

ATTEMPT_LABELS = {
    "outcome": set(telemetry.ATTEMPT_OUTCOMES),
    "error_category": set(telemetry.ERROR_CATEGORIES),
}
HTTP_LABELS = set(telemetry.HTTP_DURATION_LABELS)
CATALOG_METRICS = {
    telemetry.METRIC_ATTEMPTS,
    telemetry.METRIC_DURATION,
    telemetry.METRIC_PRODUCTS,
    telemetry.METRIC_ALERTS_OPEN,
}


def cell_values(*files: bytes) -> set[str]:
    """Every SKU, name and other non-numeric cell of the uploaded files (4+ characters)."""
    values: set[str] = set()
    for data in files:
        for row in csv.reader(io.StringIO(data.decode())):
            values |= {cell for cell in row if len(cell) >= 4 and not _numeric(cell)}
    return values - {"name", "price", "quantity"}  # the header (column names are allowed)


def _numeric(cell: str) -> bool:
    try:
        float(cell)
    except ValueError:
        return False
    return True


def exported_strings(otel) -> list[str]:
    """Every string an exporter would have sent, metric labels included."""
    found: list[str] = []
    for span in otel.spans():
        found.append(span.name)
        found += [f"{k}={v}" for k, v in (span.attributes or {}).items()]
        found += [f"{k}={v}" for k, v in span.resource.attributes.items()]
        found.append(str(span.status.description))
        for event in span.events:
            found.append(event.name)
            found += [f"{k}={v}" for k, v in (event.attributes or {}).items()]
    for record in otel.logs():
        found.append(str(record.body))
        found += [f"{k}={v}" for k, v in (record.attributes or {}).items()]
    for point in otel.points():
        found.append(point.metric)
        found += [f"{k}={v}" for k, v in point.attributes.items()]
    return found


def assert_labels_allowed(otel) -> None:
    points = otel.points()
    names = {p.metric for p in points}
    assert names <= CATALOG_METRICS | {telemetry.HTTP_DURATION}, names
    for point in points:
        if point.metric == telemetry.METRIC_ATTEMPTS:
            assert set(point.attributes) == set(ATTEMPT_LABELS), point
            for key, value in point.attributes.items():
                assert value in ATTEMPT_LABELS[key], point
        elif point.metric == telemetry.METRIC_DURATION:
            assert set(point.attributes) <= {"outcome"}, point
            assert point.attributes.get("outcome", "SUCCEEDED") in ATTEMPT_LABELS["outcome"]
        elif point.metric in (telemetry.METRIC_PRODUCTS, telemetry.METRIC_ALERTS_OPEN):
            assert point.attributes == {}, point
        else:
            assert set(point.attributes) <= HTTP_LABELS, point
            route = point.attributes.get("http.route")
            assert route is None or route.startswith("/") and not any(c.isdigit() for c in route)


@pytest.fixture
def otel_live_server(otel, make_client, database_url, migrated_engine) -> Iterator[str]:
    """The instrumented app under a real uvicorn server (as in `test_log_privacy.py`)."""
    make_client(DATABASE_URL=database_url)
    from app.main import create_app

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_config=None, lifespan="off")
    )
    thread = threading.Thread(target=server.run, name="ciw12-uvicorn", daemon=True)
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


def test_metrics_count_attempts_and_products(otel, otel_client, migrated_engine, ns):
    upload(otel_client, ns.name(), VALID)
    upload(otel_client, ns.name(), INVALID, filename="invalid.csv")

    assert otel.value(telemetry.METRIC_PRODUCTS) == 3  # the rows of valid.csv only
    assert otel.value(telemetry.METRIC_ATTEMPTS, outcome="SUCCEEDED", error_category="none") == 1
    assert (
        otel.value(telemetry.METRIC_ATTEMPTS, outcome="FAILED", error_category="VALIDATION_ERROR")
        == 1
    )
    assert otel.value(telemetry.METRIC_DURATION, outcome="SUCCEEDED")[0] == 1
    assert otel.value(telemetry.METRIC_DURATION, outcome="FAILED")[0] == 1
    [open_now] = rows(
        migrated_engine,
        "SELECT count(*) AS n FROM alerts WHERE status IN ('OPEN', 'IN_PROGRESS')",
    )
    assert otel.value(telemetry.METRIC_ALERTS_OPEN) == open_now["n"]
    http = [p for p in otel.points() if p.metric == telemetry.HTTP_DURATION]
    assert {p.attributes["http.route"] for p in http} == {"/api/imports"}
    assert_labels_allowed(otel)


def test_a_writer_that_loses_the_race_increments_nothing(otel, isolated_db):
    """The sweep ends the attempt first: it counts it; the late attempt counts nothing."""
    from app.db import get_sessionmaker
    from app.schemas.upload import UploadRequest

    import_id = importer.create_import(
        UploadRequest(
            vendor_name="Race Vendor",
            filename="valid.csv",
            data=VALID,
            inject_transient_failure=False,
        )
    )
    with get_sessionmaker()() as session, session.begin():
        attempt_id = importer.begin_attempt(session, import_id, 1)
    assert importer.sweep_stuck_imports() == 1

    importer.process_attempt(import_id, attempt_id, 1)

    attempts = [p for p in otel.points() if p.metric == telemetry.METRIC_ATTEMPTS]
    assert [(p.attributes, p.value) for p in attempts] == [
        ({"outcome": "FAILED", "error_category": "INTERNAL_ERROR"}, 1)
    ]
    assert otel.value(telemetry.METRIC_DURATION, outcome="FAILED")[0] == 1
    assert otel.value(telemetry.METRIC_PRODUCTS) in (None, 0)


def test_no_catalog_content_in_any_signal(
    otel,
    otel_client,
    otel_live_server,
    db_faults,
    migrated_engine,
    ns,
    capfd,
    monkeypatch,  # noqa: F811
):
    monkeypatch.setenv("ANTHROPIC_API_KEY", CANARY_KEY)
    stream = io.StringIO()
    telemetry.setup_logging(stream)
    try:
        upload(otel_client, ns.name(CANARY_VENDOR), CANARY_VALID, filename=CANARY_FILE)
        upload(otel_client, ns.name(CANARY_VENDOR), VALID)
        upload(otel_client, ns.name(CANARY_VENDOR), CANARY_INVALID, filename=CANARY_FILE)
        upload(otel_client, ns.name(CANARY_VENDOR), INVALID, filename=CANARY_FILE)
        body = injected(otel_client, ns.name(CANARY_VENDOR))
        alert_id, import_id = body["alert"]["id"], body["id"]
        script = [
            fake.call("get_import_incident", alert_id=alert_id),
            fake.call("retry_failed_import", import_id=import_id),
            fake.call("resolve_alert", f"done, not {CANARY_VENDOR}", alert_id=alert_id),
        ]
        assert run_claimed(fake.FakeAnthropic(script), alert_id, import_id).outcome == "RESOLVED"

        # #40's double failure: the upsert fails with a message quoting the canaries,
        # then the failure write fails too; the request ends in the stable 500.
        db_faults("products_trigger")
        db_faults("alerts_trigger")
        capfd.readouterr()
        response = httpx.post(
            f"{otel_live_server}/api/imports",
            data={"vendor_name": ns.name(VENDOR)},
            files={"file": (FILENAME, CANARY_CSV, "text/csv")},
            timeout=60,
        )
        server_output = capfd.readouterr()
    finally:
        telemetry.setup_logging()
    assert response.status_code == 500

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    unhandled = [line for line in lines if line["message"].startswith("unhandled ")]
    assert [line["message"] for line in unhandled] == [
        "unhandled ProgrammingError in POST /api/imports"
    ]
    assert set(unhandled[0]) <= {"timestamp", "level", "logger", "message", "trace_id", "span_id"}
    output = server_output.out + server_output.err
    assert "Exception in ASGI application" not in output
    assert "Traceback" not in output

    # The 500's server span: the exception's type only.
    [server] = [
        s
        for s in otel.spans("POST /api/imports")
        if s.kind == SpanKind.SERVER and s.attributes.get("http.response.status_code") == 500
    ]
    assert server.attributes["exception.type"] == "ProgrammingError"
    assert server.status.status_code == StatusCode.ERROR
    assert not server.events
    exported_unhandled = [r for r in otel.logs() if str(r.body).startswith("unhandled ")]
    assert len(exported_unhandled) == 1
    assert "exception.message" not in exported_unhandled[0].attributes

    forbidden = {
        CANARY_VENDOR,
        CANARY_FILE,
        CANARY_KEY,
        VENDOR,
        FILENAME,
        "CANARYCELL40",
        "CANARYSKU40",
        "CANARYNAME40",
        migrated_engine.url.render_as_string(hide_password=False),
        "postgresql+psycopg",
        "exception.message",
        "exception.stacktrace",
        "Traceback",
    } | cell_values(CANARY_VALID, CANARY_INVALID, fixture_bytes("valid.csv"), INVALID)
    haystack = exported_strings(otel) + [stream.getvalue(), output]
    lowered = [text.casefold() for text in haystack]
    leaks = sorted(f for f in forbidden if any(f.casefold() in text for text in lowered))
    assert not leaks, leaks
    for span in otel.spans():
        assert not span.events, span.name
        assert span.status.description is None, span.name
    assert_labels_allowed(otel)


def test_exc_info_exports_the_exception_type_only(otel):
    stream = io.StringIO()
    telemetry.setup_logging(stream)
    try:
        try:
            raise ValueError("CANARYMESSAGE12 [parameters: {'sku': 'CANARYSKU12'}]")
        except ValueError:
            telemetry.log.exception("canary failure for import 7", extra={"import_id": 7})
    finally:
        telemetry.setup_logging()

    [line] = [json.loads(x) for x in stream.getvalue().splitlines() if "canary failure" in x]
    assert line["exception_type"] == "ValueError"
    [record] = [r for r in otel.logs() if "canary failure" in str(r.body)]
    attributes: dict[str, Any] = dict(record.attributes)
    assert attributes == {"import_id": 7, "exception.type": "ValueError"}
    assert "CANARY" not in stream.getvalue().replace("canary failure", "")
    assert "CANARY" not in str(record.body)
