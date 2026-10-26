# Telemetry smoke check (CIW-09.1, #12), 2026-10-26

Text only, with no screenshots (those are #13's) and no catalog content. Run against a local stack from branch `fp-12-otel-instrumentation` with its Compose defaults (`OTEL_SDK_DISABLED=false` for `app` and `oncall-agent`, endpoint `http://otel-lgtm:4318`). The stack ran as its own project with other host ports: `-p ciw12`, `APP_PORT=8012`, `DB_PORT=5442`, and an override file mapping Grafana to 3012. In the default setup the same commands use 8000 / 5432 / 3000.

## Stack
```
docker compose -p ciw12 -f compose.yaml -f <override: otel-lgtm ports 3012:3000> up --build -d app oncall-agent otel-lgtm
curl http://localhost:8012/api/health
{"status":"ok","db":"ok","agent_enabled":false,"version":"dev"}
app:          {"timestamp": "2026-10-26T12:56:33.079Z", "level": "INFO", "logger": "app.telemetry", "message": "telemetry: exporting over OTLP/HTTP"}
oncall-agent: {"timestamp": "2026-10-26T12:56:38.190Z", "level": "INFO", "logger": "app.oncall", "message": "oncall-agent: idle because AGENT_ENABLED is not true"}
```

## The two imports (`fixtures/valid.csv`; the first with the synthetic failure injector on)
```
POST /api/imports (inject_transient_failure=true) -> id=1 FAILED TRANSIENT_STORAGE_TIMEOUT attempts[0].trace_id=d901a386471876025b7315ac3fb0fe67
POST /api/imports                                 -> id=2 COMPLETED attempts[0].trace_id=b01994fc3e7ea9856851515f4b96e436
GET /api/imports/1 -> attempt 1 FAILED TRANSIENT_STORAGE_TIMEOUT d901a386471876025b7315ac3fb0fe67
```
**Attempt trace id (from the API): `d901a386471876025b7315ac3fb0fe67`.** The worker was idle (no credentials). The agent-run trace is covered by the in-memory tests.

## Tempo
```
GET http://localhost:3012/api/datasources/proxy/uid/tempo/api/traces/d901a386471876025b7315ac3fb0fe67
ciw-app | POST /api/imports       |       |
ciw-app | catalog.import.attempt  |       | catalog.import.id=1 catalog.import.attempt_number=1 catalog.import.outcome=FAILED catalog.import.error_code=TRANSIENT_STORAGE_TIMEOUT
ciw-app | catalog.import.validate |       | catalog.import.row_count=3 catalog.import.validation_error_count=0
ciw-app | catalog.import.upsert   | ERROR | catalog.import.products_written=0 exception.type=InjectedTransientFailure
```

## Loki
```
GET .../proxy/uid/loki/loki/api/v1/query_range?query={service_name="ciw-app"} | trace_id="d901a386471876025b7315ac3fb0fe67"
alert 1 for import 1: TRANSIENT_STORAGE_TIMEOUT on attempt 1
import 1 attempt 1 failed: TRANSIENT_STORAGE_TIMEOUT (InjectedTransientFailure)
import 1 created
structured metadata (first line, trimmed): trace_id=d901a386471876025b7315ac3fb0fe67 span_id=b84dadcbd55c7be7 import_id=1 attempt_number=1 alert_id=1 severity_text=WARN scope_name=app.services.importer service_name=ciw-app
```

## Prometheus
```
GET .../proxy/uid/prometheus/api/v1/query?query=catalog_import_attempts_total
catalog_import_attempts_total{outcome="FAILED",error_category="TRANSIENT_STORAGE_TIMEOUT",service_name="ciw-app"} 1
catalog_import_attempts_total{outcome="SUCCEEDED",error_category="none",service_name="ciw-app"} 1
GET .../api/v1/label/__name__/values (catalog_ and http_server only)
catalog_import_alerts_open
catalog_import_attempts_total
catalog_import_duration_seconds_bucket / _count / _sum
catalog_products_upserted_total
http_server_request_duration_seconds_bucket / _count / _sum
catalog_import_alerts_open{service_name="ciw-app"} 1
catalog_products_upserted_total{service_name="ciw-app"} 3
sum(catalog_import_duration_seconds_count) by (outcome): FAILED 1, SUCCEEDED 1
sum(http_server_request_duration_seconds_count) by (http_route, http_request_method, http_response_status_code): GET /api/health 200: 34; POST /api/imports 201: 2; GET /api/imports/{id} 200: 1
```
No doubled `_seconds` or `_total` suffix. Apart from the resource labels the pipeline adds (`service_name`, `job`, `instance`, the SDK's), the only labels are `outcome`/`error_category`, `outcome`, and the HTTP method, route template and status code.
