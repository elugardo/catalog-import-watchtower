"""The Grafana provisioning in `observability/` (CIW-09.2): it parses, names only real series, wakes nothing.

No database and no Grafana: the files are read as text. The live check (the
dashboard and the rule appearing on a fresh stack) is the evidence run in
`_docs/evidence/2026-10-26-observability/report.md`.
"""

import json
import re
from pathlib import Path

import yaml

from app import telemetry

ROOT = Path(__file__).resolve().parents[2]
OBSERVABILITY = ROOT / "observability"
DASHBOARD = OBSERVABILITY / "grafana" / "dashboards" / "catalog-import-watchtower.json"
PROVIDER = OBSERVABILITY / "grafana" / "provisioning" / "dashboards" / "ciw.yaml"
RULES = OBSERVABILITY / "grafana" / "provisioning" / "alerting" / "ciw-alert-rules.yaml"

_SERIES_RE = re.compile(r"\bcatalog_[a-z_]+")


def _prometheus_names(otel_name: str, *, suffixes: tuple[str, ...]) -> set[str]:
    """The Prometheus series otel-lgtm makes of an OTel instrument name (dots -> underscores)."""
    base = otel_name.replace(".", "_")
    return {base + suffix for suffix in suffixes}


def exported_series() -> set[str]:
    """Every `catalog_*` series that `app/telemetry.py` exports, by its Prometheus name."""
    return (
        _prometheus_names(telemetry.METRIC_ATTEMPTS, suffixes=("_total",))
        | _prometheus_names(
            telemetry.METRIC_DURATION,
            suffixes=("_seconds_bucket", "_seconds_sum", "_seconds_count"),
        )
        | _prometheus_names(telemetry.METRIC_PRODUCTS, suffixes=("_total",))
        | _prometheus_names(telemetry.METRIC_ALERTS_OPEN, suffixes=("",))
    )


def dashboard() -> dict:
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def rule_file() -> dict:
    return yaml.safe_load(RULES.read_text(encoding="utf-8"))


def the_rule() -> dict:
    groups = rule_file()["groups"]
    rules = [rule for group in groups for rule in group["rules"]]
    assert len(rules) == 1, "exactly one Grafana alert rule"
    return rules[0]


def panel_queries() -> list[tuple[str, str]]:
    """(panel title, query) for every target of every panel."""
    return [
        (panel["title"], target["expr"])
        for panel in dashboard()["panels"]
        for target in panel.get("targets", [])
    ]


def test_the_exported_series_are_the_four_documented_ones():
    assert exported_series() == {
        "catalog_import_attempts_total",
        "catalog_import_duration_seconds_bucket",
        "catalog_import_duration_seconds_sum",
        "catalog_import_duration_seconds_count",
        "catalog_products_upserted_total",
        "catalog_import_alerts_open",
    }


def test_the_files_parse():
    assert yaml.safe_load(PROVIDER.read_text(encoding="utf-8"))["providers"]
    assert dashboard()["uid"] == "ciw-overview"
    assert dashboard()["title"] == "Catalog Import Watchtower"
    assert rule_file()["apiVersion"] == 1


def test_the_dashboard_has_the_named_panels_each_with_its_source():
    panels = {panel["title"]: panel for panel in dashboard()["panels"]}
    assert set(panels) == {
        "Imports by outcome",
        "Attempt duration (p50, p95)",
        "Open alerts",
        "Products upserted",
        "Agent runs by outcome",
        "Recent failed attempts",
    }
    for title, panel in panels.items():
        assert panel["description"].split(":")[0] in {"Prometheus", "Loki"}, title
        assert panel["datasource"]["uid"] in {"prometheus", "loki"}, title
    assert panels["Agent runs by outcome"]["datasource"]["uid"] == "loki"
    assert panels["Recent failed attempts"]["datasource"]["uid"] == "loki"


def test_every_catalog_series_in_a_panel_or_the_rule_is_exported():
    used = {name for _, query in panel_queries() for name in _SERIES_RE.findall(query)}
    used |= set(_SERIES_RE.findall(json.dumps(the_rule()["data"])))
    assert used, "the dashboard and the rule query catalog_* series"
    assert used <= exported_series(), sorted(used - exported_series())
    assert {
        "catalog_import_attempts_total",
        "catalog_import_duration_seconds_bucket",
        "catalog_import_alerts_open",
        "catalog_products_upserted_total",
    } <= used


def test_no_metric_query_groups_by_an_id():
    for title, query in panel_queries():
        for grouping in re.findall(r"by \(([^)]*)\)", query):
            labels = {label.strip() for label in grouping.split(",")}
            assert not labels & {"import_id", "alert_id", "trace_id", "attempt_number"}, title


def test_the_rule_fires_on_open_alerts_and_wakes_nothing():
    rule = the_rule()
    groups = rule_file()["groups"]
    assert rule["title"] == "Catalog import failed"
    queries = {item["refId"]: item["model"] for item in rule["data"]}
    expressions = " ".join(
        m.get("expr", "") + " " + m.get("expression", "") for m in queries.values()
    )
    assert "catalog_import_alerts_open" in expressions
    assert "> 0" in expressions
    # One aggregated series: an aggregation with no `by`, so two alerts give one instance.
    assert re.search(r"\b(max|sum)\(catalog_import_alerts_open\)", queries["A"]["expr"])
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "OK"
    assert _seconds(groups[0]["interval"]) <= 30
    assert _seconds(rule["for"]) <= 30
    annotations = rule["annotations"]
    assert "_docs/operations.md" in annotations["runbook_url"]
    assert annotations["__dashboardUid__"] == dashboard()["uid"]
    assert "notification_settings" not in rule


def test_nothing_under_observability_provisions_a_contact_point():
    for path in OBSERVABILITY.rglob("*"):
        if path.is_file() and path.suffix in {".yaml", ".yml", ".json"}:
            lines = path.read_text(encoding="utf-8").splitlines()
            # YAML comments may say what is deliberately absent; only content counts.
            text = "\n".join(line for line in lines if not line.lstrip().startswith("#"))
            for key in ("contactPoints", "receivers", "policies", "webhook", "email"):
                assert key not in text, f"{path.relative_to(ROOT)} mentions {key}"


def _seconds(duration: str) -> int:
    match = re.fullmatch(r"(\d+)([sm])", duration)
    assert match, duration
    return int(match.group(1)) * (60 if match.group(2) == "m" else 1)
