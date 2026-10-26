# Observability walkthrough (CIW-09.2, #13), 2026-10-26

No catalog content: ids, codes, counts, states and trace ids only. Times are UTC.

## Setup

- Branch `fp-13-observability-ui`, based on `main` at `44f978c` (the image was rebuilt with the branch's code before the diagnostics check below).
- Own Compose project, from `down -v`: `GRAFANA_PORT=3014 APP_PORT=8014 DB_PORT=5444 AGENT_ENABLED=false docker compose -p ciw13 up --build -d --wait`. The default `ciw` stack was not touched.
- Image `grafana/otel-lgtm:0.38.0` (digest `sha256:75cdf892daffadf3763ef61c16a6d7f8586216fce0b40bba7874a0b053121084`). Grafana `GET /api/health`: `{"database":"ok","version":"13.2.4","commit":"0e79aef9d91abf3bdadae9af15763029072fb45b"}`.
- **Recovery by hand**, not the real LLM: the CLI in `oncall-agent` (`docker compose -p ciw13 exec -T oncall-agent python -m app.oncall tools retry_failed_import <id>`, then `resolve_alert <alert_id>`), with `AGENT_ENABLED=false`. So there is no `catalog.agent.run` trace and the *Agent runs by outcome* panel shows its empty state (*No data*, screenshot 3).
- **Screenshot method:** the Claude in Chrome tool timed out on the first screenshot ("script injection timed out"), so every screenshot is a one-off headless Chromium run: `docker run --rm --add-host=host.docker.internal:host-gateway mcr.microsoft.com/playwright:v1.48.0-jammy` with a small Playwright script, pointed at `http://host.docker.internal:3014` (anonymous Grafana). Nothing was added to `compose.yaml`.

## Provisioning on a fresh project (no manual step)

```
GET /api/search?query=Catalog%20Import%20Watchtower
  uid=ciw-overview title=Catalog Import Watchtower type=dash-db url=/d/ciw-overview/catalog-import-watchtower
GET /api/v1/provisioning/alert-rules            (exactly one rule)
  uid=ciw-catalog-import-failed title=Catalog import failed for=20s noDataState=OK execErrState=OK provenance=file
```
The same rule was listed again after the second `down -v` (Run B). The `otel-lgtm` log ends with its normal start lines (every component "up and running" and the port list) and no error. The image runs Grafana with its own logging off, and a provisioning error stops Grafana. This happened once during development: an evaluation interval of 15 s is not a multiple of the 10 s scheduler tick, so the container exited and `up --wait` failed. The pinned files start cleanly.

The rule's history (screenshot 4b) also shows the two "no value" paths mapped to Normal: `Normal (Error)` right after the start, while Prometheus was not answering yet, and `Normal (NoData)` before the first gauge export.

## Run A: the fixed sequence (valid, invalid, injected, recovery)

| Step | Time | Result |
|---|---|---|
| fresh stack | 15:20:12 | attempts: no data; `max(catalog_import_alerts_open)` 0; rule Normal |
| 1. `fixtures/valid.csv` | 15:20:15 | import 1 `COMPLETED`, attempt 1 trace `74581364388364dfb59b5ee8912cea64` |
| 2. `fixtures/invalid.csv` | 15:20:16 | import 2 `FAILED` `VALIDATION_ERROR`, alert 1 `OPEN` |
| 3. `fixtures/valid.csv` + injector | 15:29:56 | import 3 `FAILED` `TRANSIENT_STORAGE_TIMEOUT`, alert 2 `OPEN`, **attempt 1 trace `1ab0e39baa6f9d79bf846e34198db25c`** (from the API) |
| 4. recovery by hand | 16:25:47 / 16:26:22 | `retry_failed_import 3`: `DONE`, import `COMPLETED`, attempts `1 FAILED`, `2 SUCCEEDED` (trace `4cb6750e00c0b249452053b70fffffb2`); `resolve_alert 2`: `DONE`, `RESOLVED` |

PromQL at the three points:

| Point | `sum by (outcome, error_category) (catalog_import_attempts_total)` | `max(catalog_import_alerts_open)` | `sum(catalog_products_upserted_total)` | Rule |
|---|---|---|---|---|
| 1. before step 3 (15:29:48) | SUCCEEDED/none 1, FAILED/VALIDATION_ERROR 1 | 1 | 3 | Firing (since step 2) |
| 2. while firing (15:35:47) | SUCCEEDED/none 1, FAILED/VALIDATION_ERROR 1, FAILED/TRANSIENT_STORAGE_TIMEOUT 1 | **2** | 3 | Firing, **one** instance, annotation "Open alerts: 2" |
| 3. after recovery (16:30:41) | SUCCEEDED/none 2, FAILED/VALIDATION_ERROR 1, FAILED/TRANSIENT_STORAGE_TIMEOUT 1 | 1 | 6 | Firing |

**Why the rule stays firing in Run A.** With the worker disabled, step 2's `VALIDATION_ERROR` alert stays `OPEN`. A human cannot close it: `mark_needs_attention` needs a claim, which the CLI does not offer, and `resolve_alert` needs a `COMPLETED` import. So the gauge is 1 from step 2 on, and the rule fires before step 3 and keeps firing after the recovery. This is the documented behaviour (`_docs/operations.md` -> *Alerting*, layer 2). With the worker enabled, the run would move that alert to `NEEDS_ATTENTION`, the gauge would drop by one, and the rule would return to Normal once the recovered import's alert was also closed. Run B shows firing and then Normal with only the injected failure.

Steps 3 and 4 are an hour apart, and the metric panels have a gap from about 15:47 to 16:25. That is where the host was busy with the first headless capture (pages hung while loading), and no samples arrived in that window. After it, the series continue with the same values.

## Run B: injected failure, then back to Normal (fresh project, `down -v`)

| Time | Event | Rule state (`GET /api/prometheus/grafana/api/v1/rules`, history in screenshot 4b) |
|---|---|---|
| 16:32:44 | fresh stack | Normal (no data) |
| 16:32:45 | import 1, injector: `FAILED` `TRANSIENT_STORAGE_TIMEOUT` | Pending 16:33:53, **Alerting 16:34:10 (85 s after the upload)** |
| 16:33:49 / 16:33:55 | import 1 retried and resolved by hand. This was too early, before the rule had seen the gauge, so it was repeated with import 2 | |
| 16:34:15 | import 2, injector: `FAILED`, alert 2 `OPEN` (attempt 1 trace `c76fd9736256525f1c65f2b06114a806`) | Alerting (the gauge stayed 1) |
| 16:35:37 / 16:35:42 | `retry_failed_import 2`: `DONE`, `COMPLETED`, two attempts; `resolve_alert 2`: `DONE`, `RESOLVED` | **Normal 16:36:03 (21 s after the resolve)** |

PromQL: firing (16:35:36): attempts FAILED/TRANSIENT_STORAGE_TIMEOUT 2, SUCCEEDED/none 1; open alerts 1. After recovery (16:36:08): FAILED/TRANSIENT_STORAGE_TIMEOUT 2, SUCCEEDED/none 2; open alerts **0**; products upserted 6; rule Normal.

## `get_import_diagnostics` strings pasted into Explore

```
get_import_diagnostics 2 (Run B, rebuilt image)
  log_query   = {service_name=~"ciw-app|ciw-oncall-agent"} | import_id="2"
  trace_query = f60a2082936191d3c883348538b45b8c   (the latest attempt, attempt 2)
Loki, log_query:
  [ciw-app] import 2 created
  [ciw-app] import 2 attempt 1 failed: TRANSIENT_STORAGE_TIMEOUT (InjectedTransientFailure)
  [ciw-app] alert 2 for import 2: TRANSIENT_STORAGE_TIMEOUT on attempt 1
  [ciw-oncall-agent] import 2 attempt 2 completed: 3 products
Tempo, GET /api/traces/<trace_query>: catalog.import.attempt, catalog.import.validate, catalog.import.upsert
```
Screenshot 1 is the same Tempo lookup typed in Explore -> Tempo -> TraceQL as a bare trace id.

## Screenshots

1. `01-tempo-failed-attempt-trace.png`: Explore -> Tempo, trace `1ab0e39baa6f9d79bf846e34198db25c`. It equals the API's attempt 1 trace id of Run A import 3. The trace is `ciw-app: POST /api/imports` (201) -> `catalog.import.attempt` -> `catalog.import.validate`, then `catalog.import.upsert` in error.
2. `02-loki-logs-for-trace.png`: Explore -> Loki, `{service_name="ciw-app"} | trace_id = "1ab0e39baa6f9d79bf846e34198db25c"`. This is the query that *Logs for this span* builds from the built-in Tempo datasource (`tracesToLogsV2`, `{${__tags}} | trace_id = "${__trace.traceId}"` with `service.name` -> `service_name`). It shows the attempt's three lines: created, `attempt 1 failed: TRANSIENT_STORAGE_TIMEOUT`, and the alert line. The headless run opened the query by URL and did not click the button.
3. `03-dashboard.png`: the dashboard after Run A step 4. The panels that moved: imports by outcome, the duration quantiles, open alerts 1 -> 2 -> 1, products upserted 3 -> 6, and the two failed attempts in the table with their trace ids. *Agent runs by outcome* shows *No data*, because the recovery was done by hand. Known cosmetic issue: the table shows the time column twice.
4. `04a-rule-firing-runA.png`: the rule *Catalog import failed* in Firing, one instance, destination empty (no contact point), with its annotations. `04b-rule-normal-runB.png`: the same rule back in Normal, with the history Normal (Error) -> Normal (NoData) -> Pending -> Alerting -> Normal.

## Checks

The grep of this folder and of `observability/` for the fixture vendor and product names, the SKUs and the API-key prefix is empty; its output is in the PR. The screenshots show Grafana pages only, never the app's pages, and no token or `.env` value.