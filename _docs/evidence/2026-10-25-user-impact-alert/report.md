# 2026-10-25 - User-impact alert (UI half)

**Rubric row served:** 11 (Monitoring: a user-impact alert), the UI half. Issue [#7](https://github.com/elugardo/catalog-import-watchtower/issues/7) (CIW-05). The other half of the row, the Grafana alert rule on `catalog_import_alerts_open > 0` with its screenshot, is CIW-09.2 ([#13](https://github.com/elugardo/catalog-import-watchtower/issues/13)).

**Commit:** `4187494` on branch `fp-7-alerts-injection` (the image was built from it with `docker compose up --build`). `AGENT_ENABLED` unset, so automated recovery is disabled.

## What was shown

Every import that ends `FAILED` raises one durable `alerts` row, written in the same transaction as the `FAILED` transition. The **Demo** checkbox is a *synthetic* failure injector: it makes attempt 1 of an otherwise valid import fail with `TRANSIENT_STORAGE_TIMEOUT` before any product is written. It is not a real storage outage.

- `upload-demo-checkbox.jpg`: the Upload page with the checkbox **Demo: fail first attempt with transient storage timeout** (unchecked on load, ticked here) and its note "This is a synthetic failure injector for the demo, not a real storage outage."
- `dashboard-open-incidents.jpg`: the Dashboard after importing `fixtures/valid.csv` with the box ticked, then `fixtures/invalid.csv` without it. Failed went from 0 to 1 after the first upload and 2 after the second. **Open incidents** lists both with **automated recovery disabled**: the injected one with `TRANSIENT_STORAGE_TIMEOUT on attempt 1 (synthetic demo fault)` and the invalid one with `VALIDATION_ERROR on attempt 1: 1 validation error`.
- `import-detail-injected.jpg`: import 1 (the injected one). It shows `FAILED` / `TRANSIENT_STORAGE_TIMEOUT`, the **Demo failure injected** note, attempt 1 `FAILED` / `TRANSIENT_STORAGE_TIMEOUT` with its finish time, and the `OPEN` incident with the injected-fault reason.
- The Products page filtered to the vendor shows its empty state ("No products yet."): neither failed import wrote a product.

`GET /api/alerts` after the run:

```json
{"items":[
 {"id":2,"status":"OPEN","reason":"VALIDATION_ERROR on attempt 1: 1 validation error","claimed_at":null,"created_at":"2026-10-25T13:40:54.909000Z","updated_at":"2026-10-25T13:40:54.909000Z","import_id":2,"import_status":"FAILED","failure_code":"VALIDATION_ERROR","vendor_display_name":"<demo vendor>","filename":"invalid.csv"},
 {"id":1,"status":"OPEN","reason":"TRANSIENT_STORAGE_TIMEOUT on attempt 1 (synthetic demo fault)","claimed_at":null,"created_at":"2026-10-25T13:40:17.191234Z","updated_at":"2026-10-25T13:40:17.191234Z","import_id":1,"import_status":"FAILED","failure_code":"TRANSIENT_STORAGE_TIMEOUT","vendor_display_name":"<demo vendor>","filename":"valid.csv"}
],"total":2}
```

No catalog content in the logs: `docker compose logs app` (65 lines) searched for the four fixture SKUs, the four fixture product names, the demo vendor name (both cases) and the CSV header `sku,name` finds 0 matches. The alert lines are:

```
import 1 attempt 1 failed: TRANSIENT_STORAGE_TIMEOUT (InjectedTransientFailure)
alert 1 for import 1: TRANSIENT_STORAGE_TIMEOUT on attempt 1
alert 2 for import 2: VALIDATION_ERROR on attempt 1
```

## How to reproduce

```
docker compose down -v
docker compose up --build -d --wait
start http://localhost:8000/upload
#   vendor "<demo vendor>", fixtures/valid.csv, tick the Demo box, Import  -> FAILED / TRANSIENT_STORAGE_TIMEOUT
#   vendor "<demo vendor>", fixtures/invalid.csv, box unticked, Import     -> FAILED / VALIDATION_ERROR
start http://localhost:8000/             # dashboard-open-incidents.jpg
start http://localhost:8000/imports/1    # import-detail-injected.jpg
curl http://localhost:8000/api/alerts
docker compose logs app | grep -E "<the fixture SKUs, product names and demo vendor name>|sku,name"   # no output
```

Screenshots were taken in Chrome at 1523x784. `upload-demo-checkbox.jpg` comes from a first pass on the same build: there the browser tool set the checkbox without a React change event, so that upload went through unflagged. The stack was reset with `docker compose down -v` and the run above was repeated with a real click on the box. Only fixture data is visible. Nothing in this folder contains tokens or credentials.