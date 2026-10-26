"""OpenTelemetry for both processes: traces, metrics and logs over OTLP/HTTP (spec section 10).

`_docs/operations.md` -> *Telemetry* lists every name defined here.

**On or off.** `configure()` installs the SDK with OTLP/HTTP exporters to
`OTEL_EXPORTER_OTLP_ENDPOINT` only when `OTEL_SDK_DISABLED` is `false`
(`app.settings`; unset means off, so `uv run` and the tests export nothing).
Off, every helper here is a no-op: no exporter, no network call, no trace id
(`current_trace_id()` returns None, so `import_attempts.trace_id` stays NULL).
Export is batched on background threads, never on the request path. Tests
install in-memory exporters through `install()` whatever the variable says,
and `reset()` turns everything off again.

**No catalog content.** Spans carry ids, counts, codes and statuses only.
Nothing here records an exception's message or stack: `span()` records the
exception's class as `exception.type`, and the log handler and the JSON
formatter keep only the class of `exc_info`. Metric labels are the closed
sets of `ATTEMPT_OUTCOMES` / `ERROR_CATEGORIES` and the HTTP histogram's
method, route template, status code, scheme and protocol version.

**Logs.** `setup_logging()` writes every record to stderr as one JSON object
per line, with the current `trace_id` / `span_id` and the `LOG_FIELDS` ids a
call passes in `extra`; when the SDK is on, the same records go out through
the SDK's log handler.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import warnings
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TextIO

# The stable HTTP semantic conventions: `http.server.request.duration` in
# seconds, labelled by method, route template, status code, scheme and
# protocol version. Read once, when the FastAPI instrumentation first runs.
os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "http")

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry._logs import NoOpLoggerProvider
from opentelemetry.metrics import CallbackOptions, NoOpMeterProvider, Observation
from opentelemetry.trace import NoOpTracerProvider, Span, Status, StatusCode

log = logging.getLogger(__name__)

# ---- names (`_docs/operations.md` -> *Telemetry*) ----------------------------------------

SPAN_ATTEMPT = "catalog.import.attempt"
SPAN_VALIDATE = "catalog.import.validate"
SPAN_UPSERT = "catalog.import.upsert"
SPAN_AGENT_RUN = "catalog.agent.run"
# One span per tool call, named after the tool; a call to a name that is not a
# tool (model-written text) is named this instead.
SPAN_UNKNOWN_TOOL = "unknown_tool"

ATTR_IMPORT_ID = "catalog.import.id"
ATTR_ATTEMPT_NUMBER = "catalog.import.attempt_number"
ATTR_OUTCOME = "catalog.import.outcome"
ATTR_ERROR_CODE = "catalog.import.error_code"
ATTR_SUPERSEDED = "catalog.import.superseded"
ATTR_ROW_COUNT = "catalog.import.row_count"
ATTR_VALIDATION_ERROR_COUNT = "catalog.import.validation_error_count"
ATTR_PRODUCTS_WRITTEN = "catalog.import.products_written"
ATTR_ALERT_ID = "catalog.alert.id"
ATTR_AGENT_OUTCOME = "catalog.agent.outcome"
ATTR_AGENT_TOOL_CALLS = "catalog.agent.tool_calls"
ATTR_TOOL_OUTCOME = "catalog.agent.tool.outcome"
ATTR_EXCEPTION_TYPE = "exception.type"

METRIC_ATTEMPTS = "catalog.import.attempts"  # Prometheus: catalog_import_attempts_total
METRIC_DURATION = "catalog.import.duration"  # Prometheus: catalog_import_duration_seconds_*
METRIC_PRODUCTS = "catalog.products.upserted"  # Prometheus: catalog_products_upserted_total
METRIC_ALERTS_OPEN = "catalog.import.alerts.open"  # Prometheus: catalog_import_alerts_open
HTTP_DURATION = "http.server.request.duration"  # Prometheus: http_server_request_duration_seconds_*

SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
ATTEMPT_OUTCOMES = (SUCCEEDED, FAILED)
NO_ERROR = "none"
ERROR_CATEGORIES = ("VALIDATION_ERROR", "TRANSIENT_STORAGE_TIMEOUT", "INTERNAL_ERROR", NO_ERROR)
HTTP_DURATION_LABELS = (
    "http.request.method",
    "http.route",
    "http.response.status_code",
    "url.scheme",
    "network.protocol.version",
)
# The other instruments of the FastAPI instrumentation are dropped: the metric
# set is exactly the four `catalog_*` ones plus the HTTP duration histogram.
_DROPPED_HTTP_INSTRUMENTS = (
    "http.server.active_requests",
    "http.server.duration",
    "http.server.request.size",
    "http.server.response.size",
    "http.server.request.body.size",
    "http.server.response.body.size",
)
DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)

# The ids a log call may pass in `extra`; the only record attributes that are exported.
LOG_FIELDS = ("import_id", "attempt_number", "alert_id")

_INSTRUMENTATION_SCOPE = "ciw"


# ---- the installed state -----------------------------------------------------------------


@dataclass
class _State:
    tracer_provider: Any = field(default_factory=NoOpTracerProvider)
    meter_provider: Any = field(default_factory=NoOpMeterProvider)
    logger_provider: Any = field(default_factory=NoOpLoggerProvider)
    enabled: bool = False
    owned: bool = False  # installed by `configure()`: `shutdown()` flushes and stops it
    handler: logging.Handler | None = None
    gauge_registered: bool = False

    def __post_init__(self) -> None:
        self.tracer = self.tracer_provider.get_tracer(_INSTRUMENTATION_SCOPE)
        meter = self.meter_provider.get_meter(_INSTRUMENTATION_SCOPE)
        self.meter = meter
        self.attempts = meter.create_counter(
            METRIC_ATTEMPTS, unit="{attempt}", description="Import attempts by end state"
        )
        self.duration = meter.create_histogram(
            METRIC_DURATION,
            unit="s",
            description="Duration of finished import attempts",
            explicit_bucket_boundaries_advisory=list(DURATION_BUCKETS),
        )
        self.products = meter.create_counter(
            METRIC_PRODUCTS, unit="{product}", description="Products written by committed attempts"
        )


_lock = threading.Lock()
_state = _State()


def enabled() -> bool:
    return _state.enabled


@contextmanager
def _sdk_switched_on() -> Iterator[None]:
    """The SDK providers read `OTEL_SDK_DISABLED` themselves and turn into no-ops on `true`.

    `install()` must work whatever the variable says (tests run with `true`), so
    the variable is hidden while the providers are built.
    """
    saved = os.environ.pop("OTEL_SDK_DISABLED", None)
    try:
        yield
    finally:
        if saved is not None:
            os.environ["OTEL_SDK_DISABLED"] = saved


def _install(
    span_processor: Any, log_processor: Any, metric_reader: Any, service_name: str, owned: bool
) -> None:
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.view import DropAggregation, View
    from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
    from opentelemetry.sdk.trace import TracerProvider

    from app.settings import get_settings

    global _state
    resource = Resource.create(
        {SERVICE_NAME: service_name, SERVICE_VERSION: get_settings().app_version}
    )
    views = [View(instrument_name=HTTP_DURATION, attribute_keys=set(HTTP_DURATION_LABELS))]
    views += [
        View(instrument_name=name, aggregation=DropAggregation())
        for name in _DROPPED_HTTP_INSTRUMENTS
    ]
    with _sdk_switched_on():
        tracer_provider = TracerProvider(resource=resource)
        meter_provider = MeterProvider(
            resource=resource, metric_readers=[metric_reader], views=views
        )
        logger_provider = LoggerProvider(resource=resource)
    tracer_provider.add_span_processor(span_processor)
    logger_provider.add_log_record_processor(log_processor)
    handler = _OtlpHandler(logger_provider)
    _state = _State(
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        logger_provider=logger_provider,
        enabled=True,
        owned=owned,
        handler=handler,
    )
    logging.getLogger().addHandler(handler)


def configure(default_service_name: str) -> bool:
    """Set up JSON logging, and the SDK with OTLP export when `OTEL_SDK_DISABLED` is `false`.

    Idempotent. Returns True only when this call installed the SDK (the caller
    then owns `shutdown()`). `OTEL_SERVICE_NAME` wins over `default_service_name`.
    """
    if not any(isinstance(h, _JsonHandler) for h in logging.getLogger().handlers):
        setup_logging()
    from app.settings import get_settings

    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001 - an invalid setting: the caller reports it; stay off
        return False
    with _lock:
        if _state.enabled or settings.otel_sdk_disabled:
            return False
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        endpoint = settings.otel_exporter_otlp_endpoint.rstrip("/")
        _install(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")),
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs")),
            PeriodicExportingMetricReader(OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics")),
            settings.otel_service_name.strip() or default_service_name,
            owned=True,
        )
    log.info("telemetry: exporting over OTLP/HTTP")
    return True


def install(
    span_exporter: Any, log_exporter: Any, metric_reader: Any, service_name: str = "ciw-test"
) -> None:
    """Tests: in-memory exporters and reader, synchronous processors, whatever the env says."""
    from opentelemetry.sdk._logs.export import SimpleLogRecordProcessor
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor

    with _lock:
        _reset_locked()
        _install(
            SimpleSpanProcessor(span_exporter),
            SimpleLogRecordProcessor(log_exporter),
            metric_reader,
            service_name,
            owned=False,
        )


def shutdown() -> None:
    """Flush and stop what `configure()` installed (the CLI, the worker at exit)."""
    with _lock:
        if _state.owned:
            _reset_locked()


def reset() -> None:
    """Back to no-op telemetry, whoever installed it."""
    with _lock:
        _reset_locked()


def _reset_locked() -> None:
    global _state
    old = _state
    _state = _State()
    if old.handler is not None:
        logging.getLogger().removeHandler(old.handler)
    for provider in (old.tracer_provider, old.meter_provider, old.logger_provider):
        stop = getattr(provider, "shutdown", None)
        if callable(stop):
            try:
                stop()
            except Exception as exc:  # noqa: BLE001 - never fail a caller on the way out
                log.warning("telemetry: shutdown failed: %s", type(exc).__name__)


# ---- the FastAPI app ---------------------------------------------------------------------


def instrument_app(app: Any) -> None:
    """Server spans and the HTTP duration histogram, plus the open-alerts gauge (`app` only).

    The instrumentation wraps the whole middleware stack from the outside, so
    `app.main.UnhandledErrorMiddleware` stays the outermost user middleware and
    the instrumentation never sees an exception (it sees the 500).
    """
    if not _state.enabled:
        return
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=_state.tracer_provider,
        meter_provider=_state.meter_provider,
        exclude_spans=["receive", "send"],
    )
    with _lock:
        if not _state.gauge_registered:
            _state.meter.create_observable_gauge(
                METRIC_ALERTS_OPEN,
                callbacks=[_open_alerts],
                unit="{alert}",
                description="Alerts OPEN or IN_PROGRESS",
            )
            _state.gauge_registered = True


def _open_alerts(_options: CallbackOptions) -> list[Observation]:
    """`OPEN` plus `IN_PROGRESS` alerts at collection time; nothing when the database is down."""
    try:
        from sqlalchemy import func, select

        from app.db import get_sessionmaker
        from app.models import Alert

        with get_sessionmaker()() as session:
            count = session.execute(
                select(func.count())
                .select_from(Alert)
                .where(Alert.status.in_(("OPEN", "IN_PROGRESS")))
            ).scalar_one()
    except Exception as exc:  # noqa: BLE001 - never raise into the SDK; the type only
        log.warning("telemetry: open alerts gauge skipped: %s", type(exc).__name__)
        return []
    return [Observation(count)]


# ---- spans -------------------------------------------------------------------------------


def ids(
    *, import_id: int | None = None, attempt_number: int | None = None, alert_id: int | None = None
) -> dict[str, int]:
    """Span attributes for the ids that are known."""
    values = {
        ATTR_IMPORT_ID: import_id,
        ATTR_ATTEMPT_NUMBER: attempt_number,
        ATTR_ALERT_ID: alert_id,
    }
    return {key: value for key, value in values.items() if value is not None}


def log_ids(
    *, import_id: int | None = None, attempt_number: int | None = None, alert_id: int | None = None
) -> dict[str, int]:
    """`extra` for a log call: the `LOG_FIELDS` that are known."""
    values = {"import_id": import_id, "attempt_number": attempt_number, "alert_id": alert_id}
    return {key: value for key, value in values.items() if value is not None}


def start_span(name: str, attributes: Mapping[str, Any] | None = None) -> Span:
    """A span that is not current yet (child of the current one); see `use_span`."""
    return _state.tracer.start_span(name, attributes=attributes, record_exception=False)


@contextmanager
def use_span(span: Span, *, end_on_exit: bool = True) -> Iterator[Span]:
    """Make `span` current. An exception marks it `ERROR` with `exception.type` only, no message."""
    with trace.use_span(
        span, end_on_exit=False, record_exception=False, set_status_on_exception=False
    ):
        try:
            yield span
        except BaseException as exc:
            mark_error(span, exc)
            if end_on_exit:
                span.end()
            raise
    if end_on_exit:
        span.end()


@contextmanager
def span(name: str, attributes: Mapping[str, Any] | None = None, *, root: bool = False):
    """A current child span (or a new trace with `root=True`); exceptions as in `use_span`."""
    parent = otel_context.Context() if root else None
    started = _state.tracer.start_span(
        name, context=parent, attributes=attributes, record_exception=False
    )
    with use_span(started) as current:
        yield current


def mark_error(target: Span, exc: BaseException | None = None) -> None:
    """Status `ERROR` with no description; the exception's class only, never its message."""
    if not target.is_recording():
        return
    if exc is not None:
        target.set_attribute(ATTR_EXCEPTION_TYPE, type(exc).__name__)
    target.set_status(Status(StatusCode.ERROR))


def current_span() -> Span:
    return trace.get_current_span()


def current_trace_id() -> str | None:
    """The current trace id as 32 lowercase hex characters, or None (never 32 zeros)."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid or not context.trace_flags.sampled:
        return None
    return format(context.trace_id, "032x")


# ---- metrics -----------------------------------------------------------------------------


def record_attempt(outcome: str, error_code: str | None, duration_seconds: float | None) -> None:
    """One attempt end state that was actually written."""
    assert outcome in ATTEMPT_OUTCOMES, outcome
    category = error_code or NO_ERROR
    assert category in ERROR_CATEGORIES, category
    _state.attempts.add(1, {"outcome": outcome, "error_category": category})
    if duration_seconds is not None:
        _state.duration.record(max(duration_seconds, 0.0), {"outcome": outcome})


def record_products(count: int) -> None:
    """Products written by a committed attempt; 0 for a failed one."""
    _state.products.add(count)


# ---- logs --------------------------------------------------------------------------------


def _timestamp(created: float) -> str:
    return (
        datetime.fromtimestamp(created, UTC)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class JsonFormatter(logging.Formatter):
    """One JSON object per record: no traceback, no exception message, ever."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": _timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = trace.get_current_span().get_span_context()
        if context.is_valid:
            entry["trace_id"] = format(context.trace_id, "032x")
            entry["span_id"] = format(context.span_id, "016x")
        for key in LOG_FIELDS:
            value = getattr(record, key, None)
            if isinstance(value, int | str) and not isinstance(value, bool):
                entry[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            entry["exception_type"] = record.exc_info[0].__name__
        return json.dumps(entry, ensure_ascii=False)


class _JsonHandler(logging.StreamHandler):
    """Writes to the given stream, or to whatever `sys.stderr` is at the time of each record."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._fixed = stream
        super().__init__(stream)
        self.setFormatter(JsonFormatter())

    @property  # type: ignore[override]
    def stream(self) -> TextIO:
        return self._fixed if self._fixed is not None else sys.stderr

    @stream.setter
    def stream(self, value: TextIO) -> None:
        pass  # set by StreamHandler.__init__; the property above decides


def setup_logging(stream: TextIO | None = None) -> None:
    """The root logger writes JSON lines to `stream` (stderr by default) at INFO and up.

    Replaces an earlier JSON handler, so calling it again only rebinds the stream.
    """
    root = logging.getLogger()
    for existing in [h for h in root.handlers if isinstance(h, _JsonHandler)]:
        root.removeHandler(existing)
    root.addHandler(_JsonHandler(None if stream is sys.stderr else stream))
    if root.level == logging.NOTSET or root.level > logging.INFO:
        root.setLevel(logging.INFO)


with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from opentelemetry.sdk._logs import LoggingHandler as _SdkLoggingHandler


class _OtlpHandler(_SdkLoggingHandler):
    """The SDK's log handler, exporting only the message, the `LOG_FIELDS` and the exception type.

    The stock handler exports every `extra` attribute, the code location, and,
    from `exc_info`, `exception.message` and `exception.stacktrace`, which can
    quote catalog values (a driver message). This keeps the class name only.
    """

    def __init__(self, logger_provider: Any) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            super().__init__(logger_provider=logger_provider)
        # The SDK's own warnings (an unreachable collector) would loop back into it.
        self.addFilter(lambda record: not record.name.startswith("opentelemetry"))

    @staticmethod
    def _get_attributes(record: logging.LogRecord) -> dict[str, Any]:
        attributes: dict[str, Any] = {}
        for key in LOG_FIELDS:
            value = getattr(record, key, None)
            if isinstance(value, int | str) and not isinstance(value, bool):
                attributes[key] = value
        if record.exc_info and record.exc_info[0] is not None:
            attributes[ATTR_EXCEPTION_TYPE] = record.exc_info[0].__name__
        return attributes
