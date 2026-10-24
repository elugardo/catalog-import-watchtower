# Spec review: inconsistencies, missing decisions, smallest viable build

> **Status 2026-10-24:** Marcos accepted sections A to C; they are applied
> in `spec.md` v1.1. §F is decided: option F1, with the key kept on Marcos's
> machine only (CI uses a fake LLM, deployed environments run with the agent
> disabled). ADR-0001 (own repository) and ADR-0002 (Fly.io + Neon + GHCR)
> are accepted. **Marcos signed off `spec.md` v1.1 as final on 2026-10-24**;
> this review is closed and kept as the record of how v1.0 became v1.1.

## F. Decided: does the running project need an LLM?

The application itself never does. Uploads, validation, upserts, history and
the durable alert all work with `AGENT_ENABLED=false`; the LLM is used only
when the on-call worker handles an alert, which in practice is the recovery
demo. The question is what earns rubric row 12 ("an agent wakes on an alert
and fixes the issue", 2 points).

| Option | What runs | Needs | Rubric row 12 | Notes |
|---|---|---|---|---|
| F1 Provider API (spec as written) | worker calls one LLM provider's API with native tool calling | an API key, only while demonstrating; cents per run | 2, matches the course's definition of an on-call agent | can run in Compose and deployed; CI uses a fake LLM |
| F2 Headless coding agent on the host | worker (or a tiny responder) shells out to `claude -p` with `--allowedTools` restricted to the maintenance CLI that exposes the six tools, as module 4 did | the logged-in `claude` CLI on the host; no API key | 2 | cannot run inside Compose or deployed, so recovery is local-demo only (which is what is graded); the app's "one command" stays true because the agent is optional |
| F3 Deterministic responder, no LLM | a rule engine applies the policy table and retries | nothing | likely 0 or 1: the rubric text does not say "LLM", but the course material (module 4, the articles) defines the on-call agent as an AI agent, and peer reviewers grade against that; it also contradicts F5's own "not a hardcoded decision tree" | worst case 22/24, still a comfortable pass; F5 would have to be rewritten honestly |

Recommendation: F1 if Marcos has or will create any provider key (the
runtime dependency is a demo-time switch, not a requirement to run the app);
F2 if he wants no API key at all. F3 only if he accepts the risk on row 12.
Whichever is chosen is written into §4 F5 and `_docs/team/oncall-agent.md`,
and the spec is then declared final.

Review of `_docs/spec.md` v1.0 on 2026-10-24, against the course rubric
(`_docs/rubric.md`) and the stack table Marcos pasted (React + TS, FastAPI,
OpenAPI, SQLite locally / Postgres deployed, Pytest, Compose, GitHub Actions,
public cloud, OpenTelemetry, PM/dev/QA agents, skills with documented tool
permissions). Goal: the smallest implementation that still scores every
rubric point. Each item has a recommendation; nothing here is applied to the
spec until Marcos decides.

## A. The six simplifications that remove the most work

These are allowed by the spec's own escape hatches or change only
"recommended" sections (§8), and none costs a rubric point.

| # | Change | Why it is safe | What it removes |
|---|---|---|---|
| A1 | **One application image.** The FastAPI container serves the built SPA from `/` (multi-stage Dockerfile: `node` builds `web/dist`, the Python image copies it) and the API from `/api`. Vite's dev server with its `/api` proxy is for development only. | Rubric row 5 wants frontend + backend + storage connected; it does not care how the SPA is served. §8's `web` service is a recommendation. | nginx image and config, the proxy, CORS, a second deploy target per environment. |
| A2 | **The on-call worker is a second process of the same image** (`command: python -m app.oncall_agent`) that calls the backend *service layer* directly: the six tools are Python functions in `services/agent_tools.py` that enforce the guards and return redacted dicts. | §7 explicitly allows "a backend service layer rather than HTTP if deployed in the same repository, [if] permissions and audited behaviour remain equivalent." Rubric row 12 only needs an agent that wakes on the alert and fixes it. | The three `/api/internal/*` endpoints, the internal token, an HTTP client, a second `pyproject`, a second Dockerfile. Keep the redaction test on the tool results instead of on an HTTP payload. |
| A3 | **PostgreSQL everywhere; reject "SQLite locally".** | The product's core claims are transactional rollback, unique constraints on normalized keys, and a row lock that makes a double retry safe. SQLite behaves differently on all three, so a local SQLite would make the integration tests prove the wrong thing. Compose makes local Postgres free, and rubric row 7 wants the DB inside Compose anyway. | A second engine in the test matrix, dialect-specific upsert code, "works on my machine" surprises at deploy time. |
| A4 | **Observability stack is local only**, the single `grafana/otel-lgtm` container (Collector + Prometheus + Loki + Tempo + Grafana). Deployed environments run with the OTel exporter disabled unless Grafana Cloud turns out to be a 20-minute job. | Rubric row 10 asks that signals are collected, stored and viewable in a UI, correlated by trace id. Screenshots and a documented reviewer path from the local stack satisfy it. §10 "Grafana Cloud or equivalent for deployment" becomes optional. | Cloud telemetry credentials, a second exporter config, one more thing that can be broken on demo day. |
| A5 | **One wake-up mechanism: the worker polls the `alerts` table** (§4 F5 already says this is sufficient). A Grafana alert rule on `catalog_import_alerts_open > 0` is provisioned so a reviewer can *see* an alert fire, but it has no webhook and wakes nothing. | Rubric row 11 wants "at least one alert"; the durable `alerts` row shown in the UI is that alert, and the Grafana rule is a second, visible one. §10's "alert rule that wakes the worker" is the same requirement stated twice; pick the DB poll. | Contact points, webhook endpoint on the worker, `host.docker.internal` plumbing, notification policies. |
| A6 | **Trim the UI to what §5 says is enough:** dashboard, upload, imports (newest 50, no pagination), import detail, products (vendor filter plus a `limit`/`offset` "load more", because one import can add 500 rows). No sorting, no search, no incident page. | Rubric has no UI-quality row. | Pagination components on four tables, sorting state. |

With A1, A2 and A4, `compose.yaml` is four services: `app`, `oncall-agent`
(same image), `db`, `otel-lgtm`. Deployment per environment is one app plus
one database.

## B. Inconsistencies inside the spec

| # | Where | Problem | Recommendation |
|---|---|---|---|
| B1 | §4 F2 vs F4 | F2 says validate the whole file before any write; F4 says the injected fault fires "before product writes are committed". If a file is *both* invalid and injected, which failure wins? The retry policy depends on it. | Validation first, always. Injection fires only after validation passes, at the start of the upsert transaction. An invalid + injected file is `VALIDATION_ERROR`, never retried, and the injection flag is simply unused. |
| B2 | §4 F5 vs §10 | F5: the worker polls every ~10 s. §10: "configure an alert rule/trigger ... that wakes the on-call worker." Two wake-up mechanisms for one requirement. | A5 above: poll wakes; Grafana rule is for visibility. Reword §10. |
| B3 | §7 vs §8 (and §4 F5) | §7 defines the three internal HTTP endpoints as part of the OpenAPI contract, then says the agent "may" use the service layer instead. §8 lists `oncall-agent` as a separate component that "uses backend's internal agent API". | A2 above: decide the service-layer route and delete the three internal rows from the §7 table (or mark them "not in MVP"). The audit requirement moves to the tool functions. |
| B4 | §4 F1 vs §7 | F1 rejects "other file types/encodings and excessive sizes with a clear error" (no import record), but the 500-row limit sits next to the 256 KiB limit, and §6 wants `row_count` on the import. Is a 501-row file a 4xx or a `FAILED` import? | Pre-checks that need no parsing (content type, > 256 KiB, not UTF-8, missing field) are 4xx with no record. Row count needs parsing, so > 500 rows is a `VALIDATION_ERROR` on a `FAILED` import (one error, "file has 501 data rows, limit 500"), which also gives the operator a durable record. |
| B5 | §6 vs §4 F2 | `imports.validation_errors_json` stores "up to 20" but F2 wants the total count shown, and §6 has no column for it. | Add `validation_error_count` to `imports` (or store `{ "total": n, "errors": [...] }` in the JSON). Pick the column: it is filterable and obvious. |
| B6 | §6 vs §4 F5 | `alerts.status` has `IN_PROGRESS` and the worker must claim "at most once at a time", but nothing says what happens when a worker dies mid-claim. The alert is stuck forever. | Add `alerts.claimed_at`. On each poll, any `IN_PROGRESS` alert older than `AGENT_CLAIM_TIMEOUT_SECONDS` (default 300) goes back to `OPEN`. The attempt-limit guard makes a second run harmless. |
| B7 | §4 F3 dashboard | Counts of "completed, failed, and recovered" imports, where recovered is a subset of completed. Does "completed" include recovered? | Make them mutually exclusive: Completed (one attempt), Recovered (completed, more than one attempt), Failed. |
| B8 | §4 F5 last bullet | "Do not pretend that deterministic/manual retry is AI recovery" implies a manual retry exists, but §7 has no operator-facing retry and §2 has no users. | No manual retry in the MVP. When the agent is unavailable, the operator uploads the file again (a new import). Say so in §3 non-goals. |
| B9 | §6 statuses vs synchronous processing (§8) | `PROCESSING` is persisted, but with synchronous processing no client can ever observe it except after a crash mid-request. | Keep it: it is one enum value, and it is the honest state if the process dies between creating the import and finishing the attempt. Add one line: "an import left in `PROCESSING` after a restart is set to `FAILED` / `INTERNAL_ERROR` by a startup sweep", or accept the rare orphan and say so. The sweep is five lines; take it. |
| B10 | §4 F5 vs §4 F2 | F5 says a `NEEDS_ATTENTION` alert stays that way; F2 says the operator fixes the file and uploads again, which creates a *new* import and a *new* alert. Old `NEEDS_ATTENTION` alerts accumulate on the dashboard with no way to clear them. | Accept for the MVP and show only `OPEN` and `IN_PROGRESS` as "open incidents" on the dashboard; `NEEDS_ATTENTION` and `RESOLVED` appear under "recent". Add "acknowledge/dismiss alert" to §3 non-goals. |
| B11 | §4 F3 vs §5 | F3 implies pagination is not required; §5 says "simple pagination is required". | A6: products get `limit`/`offset`; the other lists show the newest 50. |
| B12 | §10 vs §8 | §10 requires a reviewer to inspect telemetry in a UI; §8 lists "Grafana Cloud or equivalent for deployment" as a runtime component. The rubric needs a UI, not a deployed one. | A4. |

## C. Missing implementation decisions (fill these into the spec)

Decisions an engineer agent would otherwise make differently on every issue.
Recommended value in the right column; "smallest" wins ties.

### CSV parsing and validation

| # | Decision | Recommendation |
|---|---|---|
| C1 | Delimiter, quoting, line endings | Comma only, RFC 4180 quoting via Python's `csv` default dialect, LF or CRLF. Any other delimiter shows up as a header error. |
| C2 | Header matching | Trim whitespace and the BOM, compare case-insensitively (`SKU` = `sku`). Extra, missing or duplicate headers are a single `VALIDATION_ERROR` naming them, row `1`. |
| C3 | Row numbering in errors | The **file line number** (header is line 1, first data row is line 2). That is what the operator sees in a spreadsheet or editor. State it in the UI copy ("line 3"). |
| C4 | Blank lines | Completely empty lines are ignored anywhere in the file. A line with some blank required cells is an error. "At least one data row" counts non-empty lines. |
| C5 | `sku` grammar | ASCII only: `^[A-Za-z0-9_-]{1,64}$` after trim. Uniqueness compares `casefold()`. |
| C6 | `price` grammar | After trim: `^\d{1,10}(\.\d{1,2})?$`. No `$`, no thousands separator, no sign, no exponent. Store `round(Decimal * 100)` as `BIGINT`. |
| C7 | `quantity` grammar | After trim: `^\d{1,9}$`. No `1.0`, no `1e3`. |
| C8 | `name` | Trim; 1–120 characters; any printable Unicode. |
| C9 | `vendor_name` (unspecified today) | Trim; 1–80 characters; non-blank; any printable Unicode. `normalized_name = casefold()`. A blank or too-long vendor is a 400 `MISSING_FIELD` / `INVALID_FIELD` with no import record. |
| C10 | Vendor created even if the import fails? | Yes (the import row needs the FK). Vendors with zero products show in the filter; acceptable. |
| C11 | Size limit enforcement | Read at most 256 KiB + 1 byte from the upload stream; never trust `Content-Length`. 413 `FILE_TOO_LARGE`. |
| C12 | Content-type check | Accept `text/csv`, `application/vnd.ms-excel`, `application/octet-stream` and `text/plain` (browsers disagree), but always require a `.csv` filename and valid UTF-8. Reject anything else with 400 `INVALID_CONTENT_TYPE`. |
| C13 | Error cap | Collect all errors, store the first 20 plus the total, stop validating at 1 000 errors to bound work. |

### Import, upsert, attempts

| # | Decision | Recommendation |
|---|---|---|
| C14 | Upsert when values are unchanged | Update unconditionally (`updated_at` moves). Simplest, and `product_count` = rows in the file. |
| C15 | `import_attempts.status` values (unspecified) | `RUNNING`, `SUCCEEDED`, `FAILED`. |
| C16 | `imports.failure_code` after a successful retry | Cleared to `NULL`; the failed attempt keeps its `error_code`. |
| C17 | `imports.row_count` when the header is invalid | Count of non-empty data lines anyway (cheap and useful); `0` if the file is empty. |
| C18 | Transaction boundaries | Attempt row and status transitions are committed in their own short transactions; only the product upsert runs in the big one. A crash can leave `PROCESSING` (see B9) but never a half-written catalog. |
| C19 | Double-retry safety | `SELECT … FOR UPDATE` on the import row inside `retry`; after acquiring the lock re-read status and attempt count; if the guard fails, return the current state as a no-op (not an error) so a duplicate call is harmless. |
| C20 | Vendor find-or-create race | Insert with `ON CONFLICT (normalized_name) DO NOTHING` then select. |
| C21 | Real DB timeouts | Map an actual `OperationalError` during the upsert to `TRANSIENT_STORAGE_TIMEOUT` as well, so the policy is not purely synthetic; everything else is `INTERNAL_ERROR`. |
| C22 | CSV retention | Never deleted in the MVP; say so in §3. |

### Alerts and the on-call agent

| # | Decision | Recommendation |
|---|---|---|
| C23 | LLM provider and model | One provider, chosen by Marcos by which API key he already has, through that provider's official SDK with native tool calling. A small, cheap model is enough: the task is six tools and one decision. `LLM_PROVIDER`, `LLM_MODEL` and the key come from env; no abstraction layer beyond one module. |
| C24 | `agent_actions.action` values (unspecified) | `RUN_STARTED`, `TOOL_CALL`, `DECISION`, `RUN_FINISHED`, `ERROR`. `tool_name`, `result` (short JSON) and `reason_summary` as in §6. |
| C25 | Where the worker records actions | With A2, directly through the service layer; every tool function writes its own `TOOL_CALL` row, the loop writes the rest. |
| C26 | Run bounds | Max 8 tool calls, 120 s wall time, one conversation per alert; on exceeding → `NEEDS_ATTENTION("agent run exceeded limits")`. |
| C27 | "Agent unavailable" in the UI | The API reads the same `AGENT_ENABLED` and key presence and exposes `agent_enabled` on `/api/health`; the UI shows "automated recovery disabled" on open alerts when false. No heartbeat in the MVP. |
| C28 | `get_import_diagnostics` content | Static templates: the Loki and Tempo query strings for this import/trace and the counts already in the incident. It exists because the spec names six tools; keep it cheap. |
| C29 | Stale claims | B6. |
| C30 | Agent prompt source of truth | `_docs/team/oncall-agent.md`; the system prompt is a string in the worker module with the policy table copied verbatim. |

### API, UI, operations

| # | Decision | Recommendation |
|---|---|---|
| C31 | Ids | Integer `BIGSERIAL`. |
| C32 | List shape and limits | `{ items, total }`, `limit` default 50 / max 100, `offset`; newest first. `GET /api/products` without `vendor_id` returns all vendors. |
| C33 | `/api/health` semantics | Always 200 when the process is up, body `{ status, db: ok|error, agent_enabled, version }` (version = image SHA). Providers' health checks want 200; CI smoke asserts `db == ok`. |
| C34 | Migrations | Alembic; `alembic upgrade head` runs in the app container's entrypoint before the server starts. Single instance per environment makes this safe. Rollback relies on additive-only migrations (already in §11). |
| C35 | Image and registry | One image, GHCR, tags `sha-<commit>` and `dev`/`prod` moving tags for convenience; promotion deploys by SHA tag. |
| C36 | Provider | ADR-0002 (proposed Fly.io, one app per environment with the worker as a process group, managed Postgres per environment). Decide before issue 09 so the exporter config is written once. |
| C37 | Repository | ADR-0001 (proposed own public repository). Decide before issue 01. |
| C38 | Demo data | None seeded. The demo script imports the fixtures live; the dev environment keeps whatever was imported during rehearsal. |
| C39 | Open-alerts gauge | An OpenTelemetry observable gauge whose callback counts `OPEN` + `IN_PROGRESS` alerts on each collection. No counters to keep in sync. |

## D. Rubric check of the simplified design

| Rubric row | Earned by | Points |
|---|---|---|
| 1 Problem description | README (issue 11) | 2 |
| 2 Product specification | spec + public issues with criteria + agent comments (issue 07) | 2 |
| 3 Agent team | `_docs/team/*`, `process.md` (done) | 2 |
| 4 Context management | `AGENTS.md` → modular docs (done) | 2 |
| 5 Application | one image + Postgres in Compose, persisted imports | 2 |
| 6 Testing | pytest unit + integration on Postgres + Vitest, one command | 2 |
| 7 Containerization | `docker compose up --build` starts app, worker, db, telemetry | 2 |
| 8 Deployment | dev and prod URLs on the chosen provider | 2 |
| 9 CI/CD | PR CI, auto dev deploy, manual prod promotion by SHA, rollback doc | 3 |
| 10 Observability | local otel-lgtm, trace id across spans/logs, metrics, screenshots + reviewer path | 2 |
| 11 Alerting | durable `alerts` row shown in UI + provisioned Grafana rule | 1 |
| 12 On-call agent | worker with real tool calling, recorded real-LLM run | 2 |
| | | **24 / 24** |

Nothing in sections A to C lowers a row. The rows most at risk during the
build are 9 (needs the second environment to exist) and 12 (needs the
recorded real-LLM run); `backlog.md` already schedules them early.

## E. Spec edits to make, in order

1. §8: replace the five runtime components with four (`app` serving SPA +
   API, `oncall-agent` as the same image, `db`, `observability` local
   `otel-lgtm`); state Postgres everywhere explicitly against the SQLite
   option; mark deployed telemetry optional.
2. §7: remove (or mark "not in MVP") the three internal endpoints and the
   internal token; add "agent tools are service-layer functions with the
   same guards and audit rows".
3. §4 F4: "injection fires only after validation passes" (B1).
4. §4 F1/F2: the 4xx-vs-validation split (B4), the row-numbering and
   grammar decisions (C1–C9, C12).
5. §6: add `imports.validation_error_count`, `alerts.claimed_at`, the
   attempt and action enums (B5, B6, C15, C24).
6. §4 F3 / §5: exclusive dashboard counts (B7), the pagination rule (B11),
   "open incidents" definition (B10).
7. §10: one wake-up mechanism (B2); health semantics (C33).
8. §3: add the new non-goals: manual retry, alert acknowledgement, CSV
   retention/cleanup, deployed telemetry, pagination beyond products.
9. §8 / §11: provider and model choice (C23), migrations at startup (C34),
   image tags (C35), pointers to ADR-0001/0002.

Once these are in, bump the spec to v1.1 and declare it final; the PM can
then publish the backlog.
