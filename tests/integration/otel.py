"""In-memory OpenTelemetry for tests (#12): what the app and the worker would have exported.

`Captured` wraps the in-memory span exporter, log exporter and metric reader
that `app.telemetry.install` puts in place of OTLP. The `otel` fixture
(`tests/integration/conftest.py`) installs one per test and turns telemetry
off again afterwards, so every other test still runs with telemetry off.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def hex_trace_id(value: int) -> str:
    return format(value, "032x")


@dataclass
class Point:
    metric: str
    attributes: dict[str, Any]
    value: Any  # sum or gauge value; for a histogram, (count, sum)


@dataclass
class Captured:
    span_exporter: InMemorySpanExporter = field(default_factory=InMemorySpanExporter)
    log_exporter: InMemoryLogRecordExporter = field(default_factory=InMemoryLogRecordExporter)
    metric_reader: InMemoryMetricReader = field(default_factory=InMemoryMetricReader)

    def spans(self, name: str | None = None) -> list[Any]:
        found = list(self.span_exporter.get_finished_spans())
        return [s for s in found if name is None or s.name == name]

    def span(self, name: str) -> Any:
        [only] = self.spans(name)
        return only

    def logs(self) -> list[Any]:
        return [getattr(d, "log_record", d) for d in self.log_exporter.get_finished_logs()]

    def points(self) -> list[Point]:
        data = self.metric_reader.get_metrics_data()
        points: list[Point] = []
        for resource in data.resource_metrics if data else []:
            for scope in resource.scope_metrics:
                for metric in scope.metrics:
                    for point in metric.data.data_points:
                        value = (point.count, point.sum) if hasattr(point, "count") else point.value
                        points.append(Point(metric.name, dict(point.attributes or {}), value))
        return points

    def value(self, metric: str, **attributes: Any) -> Any:
        """The cumulative value of one series, or None when it has no point."""
        for point in self.points():
            if point.metric == metric and point.attributes == attributes:
                return point.value
        return None

    def children(self, parent: Any) -> list[Any]:
        return [
            s
            for s in self.spans()
            if s.parent is not None and s.parent.span_id == parent.context.span_id
        ]
