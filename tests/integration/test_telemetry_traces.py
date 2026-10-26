"""Traces, the stored trace id and the log/trace join, on in-memory exporters (#12).

The app runs with `app.telemetry.install` in place of OTLP (`otel`,
`otel_client`): the same spans, log records and metric points that would be
exported, collected in memory.
"""

import io
import json
import logging

from opentelemetry.trace import SpanKind, StatusCode

from app import telemetry
from app.services import agent_tools
from tests.integration.otel import hex_trace_id
from tests.integration.tooling import INVALID, VALID, attempt_rows, injected, upload
from tests.oncall import fake_llm as fake
from tests.oncall.helpers import run_claimed


def recovery(alert_id: int, import_id: int) -> fake.FakeAnthropic:
    return fake.FakeAnthropic(
        [
            fake.call("get_import_incident", alert_id=alert_id),
            fake.call("retry_failed_import", import_id=import_id),
            fake.call("resolve_alert", "Attempt 2 completed; resolving.", alert_id=alert_id),
        ]
    )


def test_a_valid_upload_is_one_trace_from_the_request_to_the_upsert(
    otel, otel_client, migrated_engine, ns
):
    body = upload(otel_client, ns.name(), VALID)

    server = next(s for s in otel.spans("POST /api/imports") if s.kind == SpanKind.SERVER)
    attempt = otel.span(telemetry.SPAN_ATTEMPT)
    assert attempt.parent.span_id == server.context.span_id
    assert attempt.context.trace_id == server.context.trace_id
    assert dict(attempt.attributes) == {
        "catalog.import.id": body["id"],
        "catalog.import.attempt_number": 1,
        "catalog.import.outcome": "SUCCEEDED",
    }
    validate = otel.span(telemetry.SPAN_VALIDATE)
    upsert = otel.span(telemetry.SPAN_UPSERT)
    assert {validate.parent.span_id, upsert.parent.span_id} == {attempt.context.span_id}
    assert dict(validate.attributes) == {
        "catalog.import.row_count": 3,
        "catalog.import.validation_error_count": 0,
    }
    assert dict(upsert.attributes) == {"catalog.import.products_written": 3}
    assert upsert.status.status_code != StatusCode.ERROR

    # The attempt's trace id: stored, returned by the API, 32 lowercase hex.
    [row] = attempt_rows(migrated_engine, body["id"])
    assert row["trace_id"] == hex_trace_id(attempt.context.trace_id)
    assert body["attempts"][0]["trace_id"] == row["trace_id"]
    detail = otel_client.get(f"/api/imports/{body['id']}")
    assert detail.json()["attempts"][0]["trace_id"] == row["trace_id"]
    assert otel.spans("GET /api/imports/{id}"), [s.name for s in otel.spans()]


def test_a_validation_failure_has_no_upsert_span(otel, otel_client, ns):
    body = upload(otel_client, ns.name(), INVALID, filename="invalid.csv")

    attempt = otel.span(telemetry.SPAN_ATTEMPT)
    assert attempt.attributes["catalog.import.outcome"] == "FAILED"
    assert attempt.attributes["catalog.import.error_code"] == "VALIDATION_ERROR"
    validate = otel.span(telemetry.SPAN_VALIDATE)
    assert (
        validate.attributes["catalog.import.validation_error_count"]
        == (body["validation_error_count"])
    )
    assert otel.spans(telemetry.SPAN_UPSERT) == []


def test_injected_failure_and_fake_llm_recovery(otel, otel_client, migrated_engine, ns):
    body = injected(otel_client, ns.name())
    alert_id, import_id = body["alert"]["id"], body["id"]

    summary = run_claimed(recovery(alert_id, import_id), alert_id, import_id)
    assert summary.outcome == "RESOLVED"

    first, second = sorted(
        otel.spans(telemetry.SPAN_ATTEMPT),
        key=lambda s: s.attributes["catalog.import.attempt_number"],
    )
    assert first.attributes["catalog.import.error_code"] == "TRANSIENT_STORAGE_TIMEOUT"
    assert second.attributes["catalog.import.outcome"] == "SUCCEEDED"
    failed_upsert = next(s for s in otel.children(first) if s.name == telemetry.SPAN_UPSERT)
    assert failed_upsert.status.status_code == StatusCode.ERROR
    assert failed_upsert.status.description is None
    assert failed_upsert.attributes["catalog.import.products_written"] == 0
    assert failed_upsert.attributes["exception.type"] == "InjectedTransientFailure"
    assert not failed_upsert.events  # no recorded exception, no message

    # The run is its own trace; each tool call a child; attempt 2 under the retry's span.
    run = otel.span(telemetry.SPAN_AGENT_RUN)
    assert run.parent is None
    assert dict(run.attributes) == {
        "catalog.alert.id": alert_id,
        "catalog.import.id": import_id,
        "catalog.agent.outcome": "RESOLVED",
        "catalog.agent.tool_calls": 3,
    }
    tools = otel.children(run)
    assert [t.name for t in tools] == [
        "get_import_incident",
        "retry_failed_import",
        "resolve_alert",
    ]
    for tool in tools:
        assert dict(tool.attributes) == {
            "catalog.alert.id": alert_id,
            "catalog.import.id": import_id,
            "catalog.agent.tool.outcome": "DONE",
        }
    assert second.parent.span_id == tools[1].context.span_id

    rows = attempt_rows(migrated_engine, import_id)
    assert [r["trace_id"] for r in rows] == [
        hex_trace_id(first.context.trace_id),
        hex_trace_id(run.context.trace_id),
    ]
    assert rows[0]["trace_id"] != rows[1]["trace_id"]
    diagnostics = agent_tools.get_import_diagnostics(import_id)["diagnostics"]
    assert diagnostics["trace_query"] is not None
    assert rows[1]["trace_id"] in diagnostics["trace_query"]

    # Every lifecycle line of the run carries the run's trace and its ids.
    run_trace = run.context.trace_id
    lines = [r for r in otel.logs() if str(r.body).startswith("oncall-agent:")]
    assert any("started" in str(r.body) for r in lines)
    assert any("finished" in str(r.body) for r in lines)
    assert len([r for r in lines if str(r.body).startswith("oncall-agent: tool ")]) == 3
    for record in lines:
        assert record.trace_id == run_trace
        assert record.attributes["alert_id"] == alert_id


def test_a_retry_through_the_cli_is_the_root_of_its_own_trace(
    otel, otel_client, migrated_engine, ns
):
    body = injected(otel_client, ns.name())

    assert agent_tools.retry_failed_import(body["id"])["import_status"] == "COMPLETED"

    second = next(
        s
        for s in otel.spans(telemetry.SPAN_ATTEMPT)
        if s.attributes["catalog.import.attempt_number"] == 2
    )
    assert second.parent is None
    assert attempt_rows(migrated_engine, body["id"])[1]["trace_id"] == hex_trace_id(
        second.context.trace_id
    )


def test_a_log_line_inside_an_attempt_carries_the_attempt_trace_id(
    otel, otel_client, migrated_engine, ns
):
    stream = io.StringIO()
    telemetry.setup_logging(stream)
    try:
        body = upload(otel_client, ns.name(), VALID)
    finally:
        telemetry.setup_logging()
    [row] = attempt_rows(migrated_engine, body["id"])

    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    [completed] = [line for line in lines if "completed: 3 products" in line["message"]]
    assert completed["trace_id"] == row["trace_id"]
    assert len(completed["span_id"]) == 16 and set(completed["span_id"]) != {"0"}
    assert (completed["import_id"], completed["attempt_number"]) == (body["id"], 1)
    assert completed["level"] == "INFO"
    assert completed["logger"] == "app.services.importer"
    assert completed["timestamp"].endswith("Z")
    [exported] = [r for r in otel.logs() if "completed: 3 products" in str(r.body)]
    assert hex_trace_id(exported.trace_id) == row["trace_id"]
    assert exported.attributes["import_id"] == body["id"]
    created = [line for line in lines if line["message"] == f"import {body['id']} created"]
    assert created and created[0]["import_id"] == body["id"]


def test_with_telemetry_off_the_trace_id_stays_null(client, migrated_engine, ns, caplog):
    caplog.set_level(logging.INFO)
    body = upload(client, ns.name(), VALID)

    assert [r["trace_id"] for r in attempt_rows(migrated_engine, body["id"])] == [None]
    assert agent_tools.get_import_diagnostics(body["id"])["diagnostics"]["trace_query"] is None
