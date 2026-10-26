"""Real OTLP exporters against a collector that is not there (#12).

With `OTEL_SDK_DISABLED=false` and the endpoint on a closed port, the app
starts, `/api/health` answers and an upload is not slowed down: export is
batched on background threads, never on the request path.
"""

import time

from app import telemetry
from tests.integration.tooling import VALID, upload

CLOSED_PORT = "http://127.0.0.1:1"


def _timed_upload(client, vendor: str) -> float:
    started = time.monotonic()
    body = upload(client, vendor, VALID)
    elapsed = time.monotonic() - started
    assert body["status"] == "COMPLETED"
    return elapsed


def test_an_unreachable_collector_slows_nothing_down(
    make_client, database_url, migrated_engine, ns
):
    off = make_client(DATABASE_URL=database_url)
    _timed_upload(off, ns.name())  # warm-up: first connections, imports
    baseline = _timed_upload(off, ns.name())

    try:
        on = make_client(
            DATABASE_URL=database_url,
            OTEL_SDK_DISABLED="false",
            OTEL_EXPORTER_OTLP_ENDPOINT=CLOSED_PORT,
            OTEL_EXPORTER_OTLP_TIMEOUT="1",  # only to keep the shutdown below short
        )
        assert telemetry.enabled()
        assert on.get("/api/health").status_code == 200
        with_export = _timed_upload(on, ns.name())
        assert with_export <= baseline + 1.0, (baseline, with_export)
    finally:
        telemetry.reset()
