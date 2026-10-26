"""`app/telemetry.py` without a database: on/off, JSON lines, the gauge's failure path (#12)."""

import io
import json
import logging
from pathlib import Path

import pytest
import yaml
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app import telemetry

REPO_ROOT = Path(__file__).resolve().parents[2]
UNREACHABLE_DB = "postgresql+psycopg://nobody:CANARYPW12@127.0.0.1:1/nothing"


@pytest.fixture(autouse=True)
def _telemetry_reset(monkeypatch, reset_caches):
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    reset_caches()
    telemetry.reset()
    yield
    telemetry.reset()
    telemetry.setup_logging()


def test_compose_turns_telemetry_on_for_app_and_oncall_agent():
    compose = yaml.safe_load((REPO_ROOT / "compose.yaml").read_text(encoding="utf-8"))
    for name in ("app", "oncall-agent"):
        service = compose["services"][name]
        env = service["environment"]
        assert env["OTEL_SDK_DISABLED"] == "${OTEL_SDK_DISABLED:-false}", name
        assert env["OTEL_EXPORTER_OTLP_ENDPOINT"] == (
            "${OTEL_EXPORTER_OTLP_ENDPOINT:-http://otel-lgtm:4318}"
        ), name
        assert service["depends_on"]["otel-lgtm"] == {"condition": "service_started"}, name
    assert compose["services"]["app"]["environment"]["OTEL_SERVICE_NAME"] == "ciw-app"
    assert compose["services"]["oncall-agent"]["environment"]["OTEL_SERVICE_NAME"] == (
        "ciw-oncall-agent"
    )
    overlay = yaml.safe_load((REPO_ROOT / "compose.test.yaml").read_text(encoding="utf-8"))
    assert overlay["services"]["test"]["environment"]["OTEL_SDK_DISABLED"] == "true"


@pytest.mark.parametrize("value", ["true", None])
def test_disabled_or_unset_is_a_no_op(monkeypatch, reset_caches, value):
    if value is None:
        monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)
    from opentelemetry.exporter.otlp.proto.http import trace_exporter

    def no_exporter(*args, **kwargs):
        raise AssertionError("no exporter may be created with telemetry off")

    monkeypatch.setattr(trace_exporter.OTLPSpanExporter, "__init__", no_exporter)
    reset_caches()

    assert telemetry.configure("ciw-app") is False
    assert not telemetry.enabled()
    with telemetry.span(telemetry.SPAN_ATTEMPT, telemetry.ids(import_id=1)):
        assert telemetry.current_trace_id() is None
    telemetry.record_attempt("SUCCEEDED", None, 0.1)  # no-ops, never raise


def test_install_works_whatever_the_variable_says():
    spans = InMemorySpanExporter()
    telemetry.install(spans, InMemoryLogRecordExporter(), InMemoryMetricReader())

    with telemetry.span(telemetry.SPAN_ATTEMPT):
        trace_id = telemetry.current_trace_id()

    [span] = spans.get_finished_spans()
    assert trace_id == format(span.context.trace_id, "032x")
    assert len(trace_id) == 32 and trace_id == trace_id.lower() and set(trace_id) != {"0"}


def test_json_lines_carry_the_fields_and_never_zero_ids():
    stream = io.StringIO()
    telemetry.setup_logging(stream)
    telemetry.install(InMemorySpanExporter(), InMemoryLogRecordExporter(), InMemoryMetricReader())
    log = logging.getLogger("app.test")

    log.info("outside a span", extra={"import_id": 5})
    with telemetry.span("catalog.test"):
        log.warning("inside a span", extra={"alert_id": 9, "attempt_number": 2})

    outside, inside = (json.loads(line) for line in stream.getvalue().splitlines())
    assert outside["message"] == "outside a span" and outside["import_id"] == 5
    assert "trace_id" not in outside and "span_id" not in outside
    assert outside["timestamp"].endswith("Z") and outside["level"] == "INFO"
    assert outside["logger"] == "app.test"
    assert len(inside["trace_id"]) == 32 and set(inside["trace_id"]) != {"0"}
    assert len(inside["span_id"]) == 16 and set(inside["span_id"]) != {"0"}
    assert (inside["alert_id"], inside["attempt_number"]) == (9, 2)


def test_the_gauge_reports_nothing_and_logs_the_type_when_the_database_is_down(
    monkeypatch, reset_caches, caplog
):
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_DB)
    reset_caches()
    caplog.set_level(logging.DEBUG)

    assert telemetry._open_alerts(None) == []

    [line] = [r for r in caplog.records if "gauge" in r.getMessage()]
    assert line.getMessage() == "telemetry: open alerts gauge skipped: OperationalError"
    assert line.exc_info is None
    assert "CANARYPW12" not in caplog.text and "127.0.0.1" not in caplog.text


def test_the_gauge_is_registered_by_the_app_only(make_client):
    reader = InMemoryMetricReader()
    telemetry.install(InMemorySpanExporter(), InMemoryLogRecordExporter(), reader)
    from app.oncall import cli  # the worker and the CLI never register it

    assert cli is not None
    assert telemetry._state.gauge_registered is False
    make_client(DATABASE_URL=UNREACHABLE_DB)
    make_client(DATABASE_URL=UNREACHABLE_DB)  # a second app: still one gauge
    assert telemetry._state.gauge_registered is True
    assert reader.get_metrics_data() is None  # database down: the gauge reports nothing
