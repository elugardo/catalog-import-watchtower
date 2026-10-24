# Catalog Import Watchtower — MVP Product & Engineering Specification

**Version:** 1.1  
**Status:** **Final** — signed off by Marcos on 2026-10-24. Applies the decisions in `spec-review.md` and ADR-0001/0002. Changes from here follow `_docs/process.md` → *When the spec is wrong* (the PM edits the spec, then the issue, then the code).  
**Purpose:** AI Dev Tools Zoomcamp 2026 final project  
**Working name:** Catalog Import Watchtower (CIW)

## 1. Executive summary

Catalog Import Watchtower is a small full-stack web application for importing vendor product catalogs from CSV files, validating records, saving valid products, and monitoring import outcomes. Users can review products and import history, inspect row-level validation errors, and see operational incidents.

Its distinctive demonstration is *automated incident response*: a demo-mode transient import failure creates an alert. A separately running **LLM-powered on-call agent** reads the incident details, invokes an allowlisted retry tool, and records its decision and outcome. Permanent validation errors require user correction instead of automatic retries.

**Priority:** Deliver a small, fully deployed and verifiable application—not a production-grade catalog platform. Meet the course rubric with evidence before adding features.

## 2. Problem, users, and goals

**Problem.** Vendor catalog imports can fail because of invalid product data or temporary technical problems. Without a simple view of import history and actionable errors, an operator cannot easily tell what happened, whether catalog data changed, or what to do next.

**Primary user:** An operations/admin user overseeing imports for several demo vendors. No authentication or user roles in the MVP; use synthetic sample data only.

**Goals:**
1. Upload a vendor catalog CSV and import its products reliably.
2. Surface useful row-level validation errors without partially changing catalog data.
3. Inspect past imports, their attempts, affected product counts, and current product catalog.
4. Demonstrate a reproducible, recoverable import failure that generates an alert.
5. Demonstrate an actual LLM agent responding to the alert using narrowly scoped tools and leaving an audit trail.
6. Show repeatable setup, tests, deployment, telemetry, and delivery automation.

**Success:** A reviewer can start the app with one command, import a valid fixture, inspect persisted products, import an invalid fixture without partial writes, and run a transient-failure demonstration in which an agent recovers the failed import. The README explains how to verify CI/CD, observability, and public deployment.

## 3. Explicit non-goals

No authentication, multi-tenant access control, supplier API integrations, webhooks from external vendors, file mapping UI, Excel/XLSX support, scheduled automatic vendor pulls, real inventory/order integrations, pricing history, approval workflows, email/SMS notifications, distributed job queue, arbitrary AI transformation of catalog data, or large files. No customer or proprietary data in demo fixtures. Also out of the MVP: an operator-facing manual retry (the operator uploads the corrected file again, which is a new import), acknowledging or dismissing alerts, deleting or expiring stored CSVs, telemetry export from deployed environments, and pagination, sorting or search on any list other than products.

## 4. User journeys and functional requirements

### F1 — Upload catalog

- The **Upload** page has a vendor name, a CSV file picker, and an **Import** button.
- `vendor_name` is trimmed and must be 1–80 printable characters. It is matched to an existing vendor by `casefold()` after trimming, and created on first import, even if that import then fails validation (so a vendor with zero products can appear in the filter).
- Upload is limited to UTF-8 CSV (optional UTF-8 BOM), maximum **256 KiB** and **500 product data rows**.
- **Checks that need no parsing are rejected before any record exists** (HTTP 4xx with the stable error shape of §7): a missing or invalid `vendor_name` or `file` (400 `MISSING_FIELD` / `INVALID_FIELD`); a filename not ending in `.csv`, or a content type other than `text/csv`, `text/plain`, `application/vnd.ms-excel`, `application/octet-stream` (400 `INVALID_CONTENT_TYPE`); bytes that are not valid UTF-8 (400 `INVALID_ENCODING`); more than 256 KiB (413 `FILE_TOO_LARGE`; the server reads at most 256 KiB + 1 byte and never trusts `Content-Length`).
- **Everything that needs parsing is a validation error on a durable `FAILED` import**, including more than 500 data rows (one error: "file has N data rows, limit 500").
- The UI shows the import result and a link to its detail page.
- Each upload creates a durable import record with filename, vendor, time, status, and stored source CSV for a possible retry.

**Acceptance:** A valid sample CSV creates a completed import; refreshing the page retains its status and resulting products.

### F2 — Validate and upsert products atomically

Required CSV columns, in any order, with no unexpected or duplicate headers:

```csv
sku,name,price,quantity
CHAIR-001,Oak Dining Chair,149.99,8
TABLE-002,Round Dining Table,499.00,3
LAMP-003,Desk Lamp,39.50,12
```

Parsing:
- Comma delimiter only, RFC 4180 quoting (Python's `csv` default dialect), LF or CRLF line endings. A leading UTF-8 BOM is stripped.
- Headers are trimmed and matched **case-insensitively** (`SKU` = `sku`). A missing, unexpected or duplicate header is a single validation error on line 1 naming the headers; nothing else is validated in that case.
- Completely empty lines are ignored anywhere in the file. "At least one data row" counts non-empty lines.
- Errors are reported with the **file line number** (the header is line 1, the first data row is line 2), the column, and a short message that may quote the offending value. The UI says "line N".

Validation rules:
- At least one data row; required fields may not be blank after trimming.
- `sku`: after trimming, ASCII `^[A-Za-z0-9_-]{1,64}$`; uniqueness within a vendor compares `casefold()`.
- `name`: trimmed string of 1–120 printable characters.
- `price`: after trimming, `^\d{1,10}(\.\d{1,2})?$` (no sign, currency symbol, thousands separator or exponent); stored as integer cents.
- `quantity`: after trimming, `^\d{1,9}$` (no `1.0`, no `1e3`).
- Duplicate SKUs **within the uploaded CSV** (compared with `casefold()`) are validation errors on every duplicate line; do not silently pick a winner.
- All errors are collected (validation stops at 1 000 to bound work); the import stores the first 20 and the total count, and the UI shows both.
- Validate the *entire file* before any product upserts. If any row is invalid, **no product records change**.
- On success, insert new products or update existing products by `(vendor, normalized SKU)`; an existing product is updated unconditionally (its `updated_at` moves even if the values are identical) and `product_count` is the number of data rows. Products absent from a later upload remain unchanged: **upsert, not full replacement**.
- Apply the complete batch in one database transaction. A runtime failure rolls back all catalog updates. The import row, each attempt row and each status transition are committed in their own short transactions, so a crash can never leave a half-written catalog, only an import stuck in `PROCESSING`, which a startup sweep marks `FAILED` / `INTERNAL_ERROR`.
- Vendor find-or-create uses `INSERT … ON CONFLICT (normalized_name) DO NOTHING` followed by a select, so two simultaneous first imports for the same vendor cannot create two vendors.

**Acceptance:** Valid new SKUs are inserted; a subsequent upload updates an existing SKU rather than duplicating it; an invalid row in an otherwise valid CSV changes no products.

### F3 — Import history, detail, and catalog views

- **Dashboard:** three mutually exclusive counts, **Completed** (status `COMPLETED`, one attempt), **Recovered** (`COMPLETED`, more than one attempt) and **Failed** (`FAILED`); a table of the newest imports; **open incidents**, defined as alerts with status `OPEN` or `IN_PROGRESS` (alerts in `NEEDS_ATTENTION` and `RESOLVED` appear in a "recent incidents" list, not as open).
- **Import history:** newest first, showing vendor, filename, timestamp, status, attempted row count, and successful product count.
- **Import detail:** status, vendor, filename, created/completed time, attempts, error category, up to 20 validation errors, incident status, and agent activity timeline.
- **Products:** filter by vendor, showing SKU, name, price, quantity, and last updated time.
- Define import statuses as `PROCESSING`, `COMPLETED`, and `FAILED`. **Recovered** is a UI label for a `COMPLETED` import with more than one attempt, not a separate persisted status.
- Show clear empty states and API-error messages. Basic responsive layout; no elaborate design system required.
- Lists show the newest 50 records. Only the products list pages (`limit`/`offset`, a "load more" control), because one import can add 500 rows.

**Acceptance:** An operator can follow an upload to the import detail and then find imported products. A failed import shows why it failed.

### F4 — Reproducible failure injection

- On the Upload page, expose a clearly labeled **Demo: fail first attempt with transient storage timeout** checkbox. Default unchecked.
- When checked, the *first* processing attempt fails with code `TRANSIENT_STORAGE_TIMEOUT` and records a failed attempt. The fault fires **only after validation has passed**, at the start of the upsert transaction and before any product write, so a file that is both invalid and injected is a plain `VALIDATION_ERROR` (never retried) and the injection flag is simply unused.
- The injected fault only occurs on attempt #1 for that import; the same saved CSV succeeds on the next attempt if valid.
- The import moves to `FAILED`, creates an incident/alert, and shows that products have **not** been partially updated.
- Validation errors use code `VALIDATION_ERROR` and are not automatically retried.
- A real database `OperationalError` during the upsert transaction is also recorded as `TRANSIENT_STORAGE_TIMEOUT`, so the recovery policy is not purely synthetic; any other unexpected exception is `INTERNAL_ERROR`.
- This checkbox is a synthetic failure injector, not an actual database outage; identify it honestly in the README and demo.

**Acceptance:** The same valid fixture succeeds normally, and with demo failure selected fails once, emits an alert, and can succeed on retry without duplicate products.

### F5 — Impact alert and LLM on-call response

- A `FAILED` import creates one durable alert tied to its import, whether caused by a transient issue or data validation. This is a **user-impact** signal: the requested catalog update did not succeed.
- A separate `oncall-agent` process (the same application image started with a different command, sharing the backend's service layer and database; no HTTP between them) polls for `OPEN` alerts every `AGENT_POLL_SECONDS` (default 10). This poll is the **only** wake-up mechanism. It claims one alert at a time with a compare-and-set `OPEN → IN_PROGRESS` that records `claimed_at`; an alert left `IN_PROGRESS` longer than `AGENT_CLAIM_TIMEOUT_SECONDS` (default 300) is returned to `OPEN` on the next poll, and the attempt-limit guard makes a second run harmless.
- It must use an actual LLM with function/tool calling, not a hardcoded decision tree masquerading as an agent. One provider, chosen by which API key Marcos already has, through that provider's official SDK; a small model is enough. `LLM_PROVIDER`, `LLM_MODEL` and the key come from environment variables read by the worker only. **The key exists only in Marcos's local `.env`:** CI uses a fake LLM, deployed environments run with `AGENT_ENABLED=false`, and the recorded real-LLM recovery (§9) is produced locally. The application itself never depends on an LLM; only the recovery demonstration does.
- The agent receives only limited operational information: import ID, status, error category/code, attempt count, timestamps, relevant structured log/trace references, and safe diagnostic summaries. **Do not send CSV rows, vendor names, product names, or credentials to the LLM.**
- Tool allowlist: `get_import_incident`, `get_import_attempts`, `get_import_diagnostics`, `retry_failed_import`, `mark_needs_attention`, `resolve_alert`. The tools are functions in the backend's service layer (`services/agent_tools.py`); each enforces its own guards, redacts its own output to the fields listed above, and writes its own audit row, so the LLM cannot reach anything else. `get_import_diagnostics` returns the observability query strings for this import and trace plus the counts already in the incident, nothing more. The same six functions are exposed to humans through a small maintenance CLI (`python -m app.oncall tools <tool> …`) with identical guards and audit rows.
- Agent policy: retry **only** `TRANSIENT_STORAGE_TIMEOUT`, at most **one automated retry** (max 2 attempts total). For `VALIDATION_ERROR`, mark `NEEDS_ATTENTION` with a concise reason; do not retry or modify the file. For an unknown error, mark `NEEDS_ATTENTION`.
- The retry reuses the exact saved CSV; it does not accept a new file and is safe against double invocation. No arbitrary shell commands, code changes, direct DB mutation, broad network access, or open-ended tool execution.
- Record each agent invocation, tool call, decision, outcome, timestamp, and associated alert/import in an auditable database timeline (`agent_actions`, with `action` one of `RUN_STARTED`, `TOOL_CALL`, `DECISION`, `RUN_FINISHED`, `ERROR`). One LLM conversation per alert, at most `AGENT_MAX_TOOL_CALLS` (default 8) tool calls and `AGENT_TIMEOUT_SECONDS` (default 120) of wall time; on exceeding either, mark `NEEDS_ATTENTION` with the reason "agent run exceeded limits".
- After successful retry, mark import `COMPLETED` and alert `RESOLVED`. If retry fails, leave the import failed and mark the alert `NEEDS_ATTENTION`.
- If `AGENT_ENABLED` is not `true` or no key is configured, imports still work, alerts remain `OPEN`, `/api/health` reports `agent_enabled: false`, and the UI shows "automated recovery disabled" on open alerts. There is no heartbeat and no operator-facing manual retry in the MVP; the operator uploads the file again. Do not pretend that a deterministic retry is AI recovery.

**Acceptance:** A real LLM call is observable in the demo; the transient-failure incident triggers a tool-based retry and ends `COMPLETED` with two attempts; a validation incident does not trigger a retry and is marked for attention.

## 5. UI scope

A simple top navigation: **Dashboard | Upload | Imports | Products**. Import detail is opened from a table link. Alert and agent activity are presented on the dashboard and import detail, avoiding an extra complex incident-management page. Lists show the newest 50 records; only the products list pages (`limit`/`offset`). No sorting, search, or filters beyond the vendor filter.

## 6. Data model (minimum)

- **vendors:** `id`, `display_name`, `normalized_name` (unique, `casefold()` of the trimmed name), `created_at`.
- **products:** `id`, `vendor_id`, `sku`, `normalized_sku`, `name`, `price_cents` (`BIGINT`), `quantity`, `updated_at`; unique `(vendor_id, normalized_sku)`.
- **imports:** `id`, `vendor_id`, `filename`, `csv_bytes` (max 256 KiB; durable for retry; never deleted in the MVP), `sha256`, `row_count` (non-empty data lines, counted even when the header is invalid; `0` for an empty file), `product_count`, `status` (`PROCESSING`, `COMPLETED`, `FAILED`), `failure_code` (`VALIDATION_ERROR`, `TRANSIENT_STORAGE_TIMEOUT`, `INTERNAL_ERROR`; cleared to `NULL` when a retry succeeds), `validation_errors_json` (first 20), `validation_error_count` (total), `inject_transient_failure`, `created_at`, `completed_at`.
- **import_attempts:** `id`, `import_id`, `attempt_number`, `status` (`RUNNING`, `SUCCEEDED`, `FAILED`), `error_code`, `trace_id`, `started_at`, `finished_at`; unique `(import_id, attempt_number)`.
- **alerts:** `id`, `import_id` (unique for MVP), `status` (`OPEN`, `IN_PROGRESS`, `RESOLVED`, `NEEDS_ATTENTION`), `reason`, `claimed_at`, `created_at`, `updated_at`.
- **agent_actions:** `id`, `alert_id`, `action` (`RUN_STARTED`, `TOOL_CALL`, `DECISION`, `RUN_FINISHED`, `ERROR`), `reason_summary`, `tool_name`, `result` (short JSON), `created_at`.

Ids are integer `BIGSERIAL`. Status and code columns are `VARCHAR` with a `CHECK` constraint, so adding a value is an additive migration. Store all timestamps in UTC (`TIMESTAMPTZ`). Use integer cents rather than floating-point prices. Use the database as the system of record for statuses and recovery audit history. For this small project, storing bounded source CSV bytes in the database is intentional and avoids a separate object-storage dependency. Migrations are Alembic and additive-only within the MVP (see §11).

## 7. API contract (OpenAPI-first)

Define these operations in `openapi.yaml` *before* implementing backend/frontend. Document request/response models and error codes. API root: `/api`.

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/imports` | Multipart form: `vendor_name`, `file`, optional `inject_transient_failure`; creates and processes import |
| `GET` | `/api/imports` | Recent imports and statuses |
| `GET` | `/api/imports/{id}` | Detail, errors, attempts, alert, agent activity |
| `GET` | `/api/vendors` | Vendor filter options |
| `GET` | `/api/products?vendor_id=...` | Catalog products; `vendor_id` optional (all vendors without it), newest `updated_at` first, `limit`/`offset` |
| `GET` | `/api/alerts` | Current/recent incident summaries |
| `GET` | `/api/health` | Always 200 while the process is up; body `{ "status": "ok"\|"degraded", "db": "ok"\|"error", "agent_enabled", "version" }`; `status` is `degraded` when `db` is `error` (version = image SHA) |

The agent's tools are **not HTTP endpoints**: the worker shares the backend's service layer (§4 F5), so the MVP has no internal routes and no internal token; the permissions and audited behaviour live in the tool functions. Concurrent duplicate retries are made safe with `SELECT … FOR UPDATE` on the import row; after the lock, status and attempt count are re-read, and a failed guard returns the current state as a no-op rather than an error. Lists return `{ "items": [...], "total": n }`, newest first, with `limit` (default 50, max 100) and `offset`. Use the stable JSON error shape `{ "code": "...", "message": "...", "details": [...] }` and return appropriate 4xx for malformed requests. A completed or failed import returned by `POST /api/imports` is still a successfully created resource (HTTP 201); its *processing status* appears in the body.

## 8. Technical architecture

**Stack (fixed):** React + TypeScript + Vite frontend; Python 3.12 FastAPI + SQLAlchemy 2 + Alembic backend managed with `uv`; **PostgreSQL 16 in both local and deployed environments** (not SQLite locally: the product's core claims are transactional rollback, unique constraints on normalized keys and a row lock for retry idempotency, which SQLite would not exercise); Pytest (unit/integration), Vitest (small frontend checks); Docker Compose; GitHub Actions; one container image. React and FastAPI intentionally follow the course examples.

**Runtime components:**

1. `app`: one image. A multi-stage Dockerfile builds the SPA and the FastAPI process serves it at `/` and the API at `/api` (same origin, no proxy, no CORS). It validates CSV, performs transactional upserts, owns import status/alert logic, runs `alembic upgrade head` from its entrypoint, and exports OpenTelemetry. During development the Vite dev server proxies `/api` to it.
2. `oncall-agent`: the same image started with `python -m app.oncall`; polls open alerts and runs the LLM tool-calling loop against the shared service layer.
3. `db`: PostgreSQL with a named persistent volume locally; a managed PostgreSQL per environment when deployed.
4. `otel-lgtm` (observability): locally the single `grafana/otel-lgtm` container (OpenTelemetry Collector, Prometheus, Loki, Tempo, Grafana) with dashboards and the alert rule provisioned from the repo. Deployed environments run with the exporter disabled unless a hosted backend is a trivial addition (optional, not required by the rubric).

No Redis, Celery, Kubernetes, nginx, additional microservices, or third-party vendor catalog APIs for the MVP. Synchronous small-file processing is acceptable; the on-call agent executes independently after the upload request returns. Source bytes and state persist in Postgres.

**Local launch:** `docker compose up --build` starts `app`, `oncall-agent`, `db` and `otel-lgtm` with one command. The app works without LLM credentials; configure the chosen provider's key and `AGENT_ENABLED=true` to enable real automated recovery. Supply `.env.example` without secrets.

## 9. Testing and acceptance scenarios

Implement automated **unit tests** for CSV parsing, header validation, price/quantity rules, duplicate SKU detection, and agent retry policy/tool guards. Implement **integration tests** against PostgreSQL for import API + DB persistence, atomic rollback, upsert behavior, alert persistence, and retry idempotency. Mock the external LLM response in CI, but run at least one **documented real-LLM demonstration** for grading. Add 1–2 frontend tests for upload and import outcome rendering.

### Must-pass scenarios

1. **Happy path:** Import `fixtures/valid.csv` for `Sample Furnishings`; see 3 products, `COMPLETED`, one attempt; refresh and confirm persistence.
2. **Upsert:** Import `fixtures/update.csv` changing `CHAIR-001` price/quantity; vendor product count does not increase for that SKU, values change.
3. **Atomic validation:** Import `fixtures/invalid.csv` containing a bad quantity among otherwise valid rows; import is `FAILED`, errors identify the CSV row, and product counts/values stay unchanged.
4. **Recovery:** Import `valid.csv` with demo failure enabled; first attempt fails with `TRANSIENT_STORAGE_TIMEOUT`, creates an alert, does not change products; real on-call agent retries once; second attempt succeeds; alert resolves and the detail page shows two attempts plus agent actions.
5. **Agent guardrails:** Validation error triggers no retry; duplicate alert processing and retry calls cannot generate a third attempt or duplicate catalog products.
6. **Reproducibility:** `docker compose up --build` starts the application; one documented command runs all unit and integration tests; public deployment opens and serves persisted records.

## 10. Observability and operational requirements

- Instrument the upload-to-import database flow and agent retry flow with OpenTelemetry spans, structured logs, and metrics. Attach the same `trace_id` to the corresponding logs and attempt record; include `import_id` and `attempt_number` as correlation fields.
- Suggested metrics: `catalog_import_attempts_total{outcome,error_category}`, `catalog_import_duration_seconds`, `catalog_products_upserted_total`, `catalog_import_alerts_open`.
- A reviewer must be able to use an observability UI to inspect a failed import's **trace, logs, and metrics**. Documentation contains a screenshot or dashboard link and query examples. The local stack is sufficient for this.
- Never export original CSV content, product names, vendor names, tokens, or credentials in telemetry. Low-cardinality metric labels only; import IDs belong in logs/traces, not metric labels.
- **User-impact alert:** Trigger on an actual `FAILED` catalog import, not just host CPU. The durable `alerts` row shown in the UI is the alert, and it is what wakes the on-call worker (by polling, §4 F5). In addition, a Grafana alert rule on `catalog_import_alerts_open > 0` is provisioned from the repo so a reviewer can watch an alert fire in the observability UI; it has no webhook and wakes nothing. `catalog_import_alerts_open` is an observable gauge whose callback counts `OPEN` + `IN_PROGRESS` alerts.
- Make incident diagnosis visible: failure code, cause, action chosen, retry execution, recovery outcome, and before/after metrics/logs.

## 11. CI/CD, deployment, rollback

- Public GitHub repository with documentation in English and a **public GitHub Issues** backlog. Each issue has acceptance criteria and links to the relevant commits/PRs; record evidence that agents used the issues.
- On every PR: backend unit and integration tests, frontend tests/build, and container build checks.
- On merge/push to `main`: build the single application image, tag it `sha-<commit>` (plus a moving `dev` tag for convenience), push to GHCR, automatically deploy to **development** and smoke-check `/api/health`. Migrations run from the container entrypoint on start.
- Production is a separate environment/database. A manually triggered GitHub Actions workflow **promotes the exact tested image tag** from development to production (no rebuild).
- Document a rollback path to the previous image SHA, including what happens to database migrations. Keep schema changes backward-compatible for the MVP.
- Provide public URLs (preferably dev and prod), environment-specific health checks, and a short deployment walkthrough or demo recording.
- Deployment: Fly.io apps `ciw-dev` and `ciw-prod`, one Neon PostgreSQL project per environment, the image public in GHCR, promotion by `flyctl deploy --image <sha tag>` behind a GitHub `production` environment approval (`_docs/adr/0002-deployment-provider.md`; repository layout in `0001`). Do not claim production promotion if only a single environment exists. No demo data is seeded; the demo imports the fixtures live.
- **Secrets never enter the repository, and deployments cannot reach other projects.** The only GitHub secret is a Fly deploy token scoped to the one app it deploys, in the environment secrets; database URLs are Fly secrets; the LLM key stays in the local `.env`. `.env*` is gitignored, `.env.example` is committed, PR CI runs a secret scan, and GitHub push protection is on. The inventory and controls are in ADR-0002 and `_docs/operations.md`.

## 12. AI-assisted development process and agent team

Define and use these **development-time roles** (distinct from the runtime on-call agent):

- **Product manager agent:** translates this spec into small GitHub Issues, with acceptance criteria and explicit exclusions; confirms feature scope.
- **Software engineer agent:** reads one issue and the relevant project docs, implements that slice, runs focused tests, documents decisions, and links changes to the issue.
- **QA/reviewer agent:** starts in a fresh context, independently tests edge cases and acceptance criteria, opens follow-up issues instead of silently changing requirements.
- **On-call operations agent (runtime):** receives failed-import alerts and uses the restricted diagnostic/retry tools in §4 F5; does not write code.

Create `AGENTS.md` as an index with project commands and links to modular docs:

```text
AGENTS.md
_docs/spec.md
_docs/process.md
_docs/architecture.md
_docs/api.md
_docs/testing.md
_docs/operations.md
_docs/team/product-manager.md
_docs/team/software-engineer.md
_docs/team/qa-engineer.md
_docs/team/oncall-agent.md
_docs/rubric.md, _docs/backlog.md, _docs/issue-template.md, _docs/adr/
.agents/skills/incident-response/SKILL.md
openapi.yaml
```

`process.md` should require: select a GitHub Issue; read acceptance criteria; implement only that issue; run tests; request an independent QA review; link commits/PR; close only after evidence is recorded. `incident-response/SKILL.md` documents the repeatable operational diagnosis and recovery routine. Include an AI-workflow section in README describing delegation, context provided, human review, and how outputs were verified; real GitHub history is stronger than a retrospective assertion.

## 13. Suggested GitHub Issues (publish as individual public issues)

| ID | Title | Acceptance focus | Priority |
|---|---|---|---|
| 01 | Scaffold app + Docker Compose + passing smoke test | One-command startup; API health; frontend renders; database persistent | P0 |
| 02 | Write OpenAPI contract and DB models | Spec-approved endpoints; migrations and constraints | P0 |
| 03 | Implement CSV validation + transactional import | Correct rows; error feedback; no partial writes; upsert | P0 |
| 04 | Build upload, history, detail, and products UI | Connected end-to-end; persisted data visible | P0 |
| 05 | Add failed-import alerts and failure injection | Deterministic transient failure; durable alert | P0 |
| 06 | Add unit/integration/frontend tests + fixtures | One documented test command; key scenarios pass | P0 |
| 07 | Create agent team docs + issue workflow evidence | Clear roles, `AGENTS.md`, modular docs, issue links | P0 |
| 08 | Add constrained LLM on-call worker + audit trail | Real tool call; transient retry; validation escalation | P1 |
| 09 | Add OpenTelemetry + observability UI | Correlated logs/metrics/traces; viewer/screenshots | P1 |
| 10 | Publish deployment + CI/CD + rollback | PR CI; dev CD; manual prod promotion; public URL | P1 |
| 11 | Prepare README, demo, and rubric evidence | Reproducible reviewer walkthrough and links | P0 |

**Scheduling note:** Start with issue 01, and complete issues 02–04 and 06 before adding visual polish. Work on agent recovery, telemetry, and deployment early enough to demonstrate them; these are not merely optional stretch features for the course rubric. Split any issue that does not fit one focused agent session.

## 14. Definition of done / reviewer demo

A project submission is ready when:

- [ ] Public repo README explains the problem, architecture, features, setup, test command, deployment, and limitations.
- [ ] Public GitHub Issues link back to acceptance criteria and agent-assisted work.
- [ ] `AGENTS.md`, modular docs, and team responsibilities exist.
- [ ] One-command local startup; connected frontend/backend/Postgres; persistent products/imports.
- [ ] Unit and integration test suites pass; screenshots or CI run links show evidence.
- [ ] Containers build and run; public deployment is accessible.
- [ ] CI tests PRs; development deployment is automatic; production promotion is manual; rollback is documented.
- [ ] Metrics, structured logs, and traces share a trace ID and are inspectable in a UI.
- [ ] A user-impact import alert is visibly raised.
- [ ] A real LLM on-call agent wakes up, investigates, retries an injected transient failure, and records the successful result; validation failures are not retried.
- [ ] Demo video/README walk-through reproduces happy path, invalid input, transient failure, and recovery.
- [ ] Submitted repo commit and links are correct; required course peer reviews are completed on time.

### Recommended 3-minute demo script

1. Open dashboard; show prior imports and product counts.
2. Upload `valid.csv`; open detail and products to show saved rows.
3. Upload `invalid.csv`; show row-level error and unchanged product data.
4. Upload `valid.csv` with injected failure; show import `FAILED` and an open alert.
5. Show the on-call agent reading diagnostics, issuing the retry tool call, and recording its decision; refresh to see `COMPLETED` with two attempts and resolved alert.
6. Open Grafana (or equivalent) and show correlated trace/logs/metrics; briefly show green GitHub Actions runs, dev/prod promotion workflow, and public URL.

## 15. Course requirements reference

- Current rubric: https://github.com/DataTalksClub/ai-dev-tools-zoomcamp/tree/main/project
- Course project requirements: https://datatalksclub.github.io/docs/courses/ai-dev-tools-zoomcamp/project/
- Course article on specification and context management: https://aishippingblog.com/p/ai-native-development-specifications
- Course article on DevOps, observability, and agent response: https://aishippingblog.com/p/devops-and-observability-for-an-ai
- Course article on agent skills/subagents: https://aishippingblog.com/p/coding-agent-building-blocks-reusable

**Rubric reminder:** The specification file alone does *not* earn the full Product Specification score; publish the acceptance criteria in a public issue tracker and demonstrate that agents used it. The runtime on-call agent is likewise not replaced by the development-time PM/engineering/QA agent roles.
